/*
 * =============================================================================
 * PARITY PROBE
 *
 * Editor console command of the parity harness (To-O3DE Project Converter):
 *
 *     parity_dump <folder>
 *
 * Writes what the running Editor holds for every editor entity of the open
 * level - what Editor Python cannot read:
 *
 *   - the prefab identity of the entity (template, instance path, alias),
 *     which joins it to the converter's trace;
 *   - its world and local transform, and its non-uniform scale;
 *   - the vertices of its model (LOD 0), as cooked;
 *   - the geometry of each collider shape the Editor built for it.
 *
 * Output, under <folder>:
 *   record.json              one record per entity
 *   probe_done.json          counts; the session script waits on it
 *   models/<key>.pos, .idx   float32 x,y,z per vertex / uint32 per index
 *   colliders/<key>.pos, .idx  the same, in the shape's own space
 *
 * All values are the engine's own: metres, Z up, right-handed.
 * Nothing in the level is changed.
 * =============================================================================
 */

#include <AzCore/Component/ComponentApplicationBus.h>
#include <AzCore/Component/Entity.h>
#include <AzCore/Component/NonUniformScaleBus.h>
#include <AzCore/Component/TransformBus.h>
#include <AzCore/Console/IConsole.h>
#include <AzCore/Interface/Interface.h>
#include <AzCore/IO/SystemFile.h>
#include <AzCore/Math/Matrix3x4.h>
#include <AzCore/Name/Name.h>
#include <AzCore/std/containers/unordered_set.h>
#include <AzCore/std/containers/vector.h>
#include <AzCore/std/string/string.h>

#include <AzFramework/Physics/Components/SimulatedBodyComponentBus.h>
#include <AzFramework/Physics/Shape.h>
#include <AzFramework/Physics/ShapeConfiguration.h>
#include <AzFramework/Physics/SimulatedBodies/RigidBody.h>
#include <AzFramework/Physics/SimulatedBodies/StaticRigidBody.h>

#include <AzToolsFramework/Entity/EditorEntityContextBus.h>
#include <AzToolsFramework/Prefab/Instance/Instance.h>
#include <AzToolsFramework/Prefab/Instance/InstanceEntityMapperInterface.h>

#include <Atom/RPI.Reflect/Model/ModelAsset.h>
#include <Atom/RPI.Reflect/Model/ModelLodAsset.h>
#include <AtomLyIntegration/CommonFeatures/Mesh/MeshComponentBus.h>

// Transform 2 exists only in engines that carry it. Without the header the
// probe simply reports no entity as serving it.
#if __has_include(<AzCore/Component/Transform2Bus.h>)
#include <AzCore/Component/Transform2Bus.h>
#define PARITY_PROBE_HAS_TRANSFORM2 1
#else
#define PARITY_PROBE_HAS_TRANSFORM2 0
#endif

namespace ParityProbe
{
    // =========================================================================
    // STATE OF ONE DUMP
    // =========================================================================

    struct Dump
    {
        AZStd::string m_folder;
        AZStd::string m_records;                            // the entity records, comma separated
        AZStd::unordered_set<AZStd::string> m_modelsWritten;
        int m_entities = 0;
        int m_meshes = 0;
        int m_meshesNotReady = 0;
        int m_shapes = 0;
        int m_writeErrors = 0;
    };

    // =========================================================================
    // TEXT AND FILES
    // =========================================================================

    static AZStd::string Quoted(AZStd::string_view text)
    {
        AZStd::string result = "\"";
        for (char character : text)
        {
            if (character == '"' || character == '\\')
            {
                result += '\\';
                result += character;
            }
            else if (static_cast<unsigned char>(character) < 0x20)
            {
                result += ' ';
            }
            else
            {
                result += character;
            }
        }
        result += "\"";
        return result;
    }

    static AZStd::string Numbers(const float* values, size_t count)
    {
        AZStd::string result = "[";
        for (size_t index = 0; index < count; ++index)
        {
            result += AZStd::string::format(index == 0 ? "%.9g" : ",%.9g", static_cast<double>(values[index]));
        }
        result += "]";
        return result;
    }

    static AZStd::string VectorJson(const AZ::Vector3& value)
    {
        const float values[3] = { value.GetX(), value.GetY(), value.GetZ() };
        return Numbers(values, 3);
    }

    static AZStd::string QuaternionJson(const AZ::Quaternion& value)
    {
        const float values[4] = { value.GetX(), value.GetY(), value.GetZ(), value.GetW() };
        return Numbers(values, 4);
    }

    // The 3x4 matrix of a transform, row by row.
    static AZStd::string MatrixJson(const AZ::Matrix3x4& matrix)
    {
        float values[12];
        for (int row = 0; row < 3; ++row)
        {
            for (int column = 0; column < 4; ++column)
            {
                values[row * 4 + column] = matrix.GetElement(row, column);
            }
        }
        return Numbers(values, 12);
    }

    static AZStd::string FileKey(AZStd::string_view text)
    {
        AZStd::string key;
        for (char character : text)
        {
            const bool keep = (character >= 'a' && character <= 'z') || (character >= 'A' && character <= 'Z')
                || (character >= '0' && character <= '9') || character == '-' || character == '.';
            key += keep ? character : '_';
        }
        return key;
    }

    static void WriteFile(Dump& dump, const AZStd::string& relativePath, const void* data, size_t size)
    {
        const AZStd::string path = dump.m_folder + "/" + relativePath;
        AZ::IO::SystemFile file;
        const int flags = AZ::IO::SystemFile::SF_OPEN_CREATE | AZ::IO::SystemFile::SF_OPEN_CREATE_PATH
            | AZ::IO::SystemFile::SF_OPEN_WRITE_ONLY;
        if (!file.Open(path.c_str(), flags))
        {
            ++dump.m_writeErrors;
            return;
        }
        if (size > 0)
        {
            file.Write(data, size);
        }
        file.Close();
    }

    static void WritePositions(Dump& dump, const AZStd::string& relativePath, const AZStd::vector<float>& positions)
    {
        WriteFile(dump, relativePath, positions.data(), positions.size() * sizeof(float));
    }

    static void WriteIndices(Dump& dump, const AZStd::string& relativePath, const AZStd::vector<AZ::u32>& indices)
    {
        WriteFile(dump, relativePath, indices.data(), indices.size() * sizeof(AZ::u32));
    }

    // =========================================================================
    // PREFAB IDENTITY
    // =========================================================================

    static AZStd::string PrefabJson(AZ::EntityId entityId)
    {
        AZStd::string templatePath;
        AZStd::string instancePath;
        AZStd::string alias;
        bool isContainer = false;

        auto* mapper = AZ::Interface<AzToolsFramework::Prefab::InstanceEntityMapperInterface>::Get();
        if (mapper)
        {
            AzToolsFramework::Prefab::InstanceOptionalReference owner = mapper->FindOwningInstance(entityId);
            if (owner.has_value())
            {
                AzToolsFramework::Prefab::Instance& instance = owner->get();
                templatePath = instance.GetTemplateSourcePath().c_str();
                instancePath = instance.GetAbsoluteInstanceAliasPath().c_str();
                isContainer = instance.GetContainerEntityId() == entityId;
                AzToolsFramework::Prefab::EntityAliasOptionalReference found = instance.GetEntityAlias(entityId);
                if (found.has_value())
                {
                    alias = found->get();
                }
            }
        }

        return AZStd::string::format(
            "{\"template\":%s,\"instancePath\":%s,\"alias\":%s,\"isContainer\":%s}",
            Quoted(templatePath).c_str(), Quoted(instancePath).c_str(), Quoted(alias).c_str(),
            isContainer ? "true" : "false");
    }

    // =========================================================================
    // MODEL
    // The vertices of level of detail 0, every mesh of it in one list.
    // A model is written once, whatever number of entities show it.
    // =========================================================================

    static AZStd::string MeshJson(Dump& dump, AZ::EntityId entityId)
    {
        AZ::Data::Asset<const AZ::RPI::ModelAsset> model;
        AZ::Render::MeshComponentRequestBus::EventResult(
            model, entityId, &AZ::Render::MeshComponentRequestBus::Events::GetModelAsset);
        if (!model.GetId().IsValid())
        {
            return "null";
        }

        ++dump.m_meshes;
        const AZStd::string hint = model.GetHint();
        const AZStd::string key = FileKey(hint);

        bool ready = model.IsReady() && model->GetLodCount() > 0 && model->GetLodAssets()[0].IsReady();
        size_t vertexCount = 0;
        size_t indexCount = 0;
        AZ::Aabb aabb = AZ::Aabb::CreateNull();

        if (ready)
        {
            aabb = model->GetAabb();
            AZStd::vector<float> positions;
            AZStd::vector<AZ::u32> indices;
            const AZ::Name positionName("POSITION");
            for (const AZ::RPI::ModelLodAsset::Mesh& mesh : model->GetLodAssets()[0]->GetMeshes())
            {
                const AZ::u32 firstVertex = static_cast<AZ::u32>(positions.size() / 3);
                const AZStd::span<const float> meshPositions = mesh.GetSemanticBufferTyped<float>(positionName);
                const AZStd::span<const AZ::u32> meshIndices = mesh.GetIndexBufferTyped<AZ::u32>();
                positions.insert(positions.end(), meshPositions.begin(), meshPositions.end());
                for (AZ::u32 index : meshIndices)
                {
                    indices.push_back(firstVertex + index);
                }
            }
            vertexCount = positions.size() / 3;
            indexCount = indices.size();
            ready = vertexCount > 0;

            if (ready && dump.m_modelsWritten.insert(key).second)
            {
                WritePositions(dump, "models/" + key + ".pos", positions);
                WriteIndices(dump, "models/" + key + ".idx", indices);
            }
        }
        if (!ready)
        {
            ++dump.m_meshesNotReady;
        }

        const AZStd::string aabbMin = aabb.IsValid() ? VectorJson(aabb.GetMin()) : AZStd::string("null");
        const AZStd::string aabbMax = aabb.IsValid() ? VectorJson(aabb.GetMax()) : AZStd::string("null");
        return AZStd::string::format(
            "{\"asset\":%s,\"assetId\":%s,\"ready\":%s,\"key\":%s,\"vertexCount\":%zu,\"indexCount\":%zu,"
            "\"aabbMin\":%s,\"aabbMax\":%s}",
            Quoted(hint).c_str(), Quoted(model.GetId().ToString<AZStd::string>()).c_str(),
            ready ? "true" : "false", Quoted(key).c_str(), vertexCount, indexCount,
            aabbMin.c_str(), aabbMax.c_str());
    }

    // =========================================================================
    // COLLIDERS
    // The shapes of every physics body the Editor built for the entity, each
    // with its geometry in the shape's own space, its pose in the body and
    // the body's world transform.
    // =========================================================================

    static void CollectShapes(AzPhysics::SimulatedBody* body, AZStd::vector<AZStd::shared_ptr<Physics::Shape>>& shapes)
    {
        if (auto* staticBody = azrtti_cast<AzPhysics::StaticRigidBody*>(body))
        {
            for (AZ::u32 index = 0; index < staticBody->GetShapeCount(); ++index)
            {
                shapes.push_back(staticBody->GetShape(index));
            }
        }
        else if (auto* rigidBody = azrtti_cast<AzPhysics::RigidBody*>(body))
        {
            for (AZ::u32 index = 0; index < rigidBody->GetShapeCount(); ++index)
            {
                shapes.push_back(rigidBody->GetShape(index));
            }
        }
    }

    static AZStd::string CollidersJson(Dump& dump, AZ::EntityId entityId)
    {
        AZStd::vector<AzPhysics::SimulatedBody*> bodies;
        AzPhysics::SimulatedBodyComponentRequestsBus::EnumerateHandlersId(
            entityId,
            [&bodies](AzPhysics::SimulatedBodyComponentRequests* handler)
            {
                AzPhysics::SimulatedBody* body = handler->GetSimulatedBody();
                if (body && AZStd::find(bodies.begin(), bodies.end(), body) == bodies.end())
                {
                    bodies.push_back(body);
                }
                return true;
            });

        AZStd::string result = "[";
        int written = 0;
        for (AzPhysics::SimulatedBody* body : bodies)
        {
            const AZ::Matrix3x4 bodyWorld = AZ::Matrix3x4::CreateFromTransform(body->GetTransform());
            AZStd::vector<AZStd::shared_ptr<Physics::Shape>> shapes;
            CollectShapes(body, shapes);

            for (const AZStd::shared_ptr<Physics::Shape>& shape : shapes)
            {
                if (!shape)
                {
                    continue;
                }
                AZStd::vector<AZ::Vector3> vertices;
                AZStd::vector<AZ::u32> indices;
                shape->GetGeometry(vertices, indices);

                AZStd::vector<float> positions;
                positions.reserve(vertices.size() * 3);
                for (const AZ::Vector3& vertex : vertices)
                {
                    positions.push_back(vertex.GetX());
                    positions.push_back(vertex.GetY());
                    positions.push_back(vertex.GetZ());
                }

                const AZStd::string key = AZStd::string::format(
                    "%llu_%d", static_cast<unsigned long long>(static_cast<AZ::u64>(entityId)), written);
                WritePositions(dump, "colliders/" + key + ".pos", positions);
                WriteIndices(dump, "colliders/" + key + ".idx", indices);

                const AZStd::pair<AZ::Vector3, AZ::Quaternion> pose = shape->GetLocalPose();
                const AZStd::shared_ptr<Physics::ShapeConfiguration> configuration = shape->GetShapeConfiguration();
                const int shapeType = configuration ? static_cast<int>(configuration->GetShapeType()) : -1;

                result += AZStd::string::format(
                    "%s{\"key\":%s,\"shapeType\":%d,\"bodyWorld\":%s,\"localPosition\":%s,\"localRotation\":%s,"
                    "\"vertexCount\":%zu,\"indexCount\":%zu}",
                    written == 0 ? "" : ",", Quoted(key).c_str(), shapeType, MatrixJson(bodyWorld).c_str(),
                    VectorJson(pose.first).c_str(), QuaternionJson(pose.second).c_str(),
                    vertices.size(), indices.size());
                ++written;
                ++dump.m_shapes;
            }
        }
        result += "]";
        return result;
    }

    // =========================================================================
    // ONE ENTITY
    // =========================================================================

    static void DumpEntity(Dump& dump, AZ::Entity* entity)
    {
        const AZ::EntityId entityId = entity->GetId();

        AZ::Transform world = AZ::Transform::CreateIdentity();
        AZ::Transform local = AZ::Transform::CreateIdentity();
        AZ::EntityId parentId;
        AZ::TransformBus::EventResult(world, entityId, &AZ::TransformBus::Events::GetWorldTM);
        AZ::TransformBus::EventResult(local, entityId, &AZ::TransformBus::Events::GetLocalTM);
        AZ::TransformBus::EventResult(parentId, entityId, &AZ::TransformBus::Events::GetParentId);

        // Non-uniform scale: only an entity that serves the bus has one.
        AZStd::string nonUniform = "null";
        if (AZ::NonUniformScaleRequestBus::FindFirstHandler(entityId) != nullptr)
        {
            AZ::Vector3 scale = AZ::Vector3::CreateOne();
            AZ::NonUniformScaleRequestBus::EventResult(scale, entityId, &AZ::NonUniformScaleRequests::GetScale);
            nonUniform = VectorJson(scale);
        }

        // Transform 2: the exact world matrix, when the entity serves it.
        AZStd::string transform2 = "null";
#if PARITY_PROBE_HAS_TRANSFORM2
        if (AZ::Transform2RequestBus::FindFirstHandler(entityId) != nullptr)
        {
            AZ::Matrix3x4 exact = AZ::Matrix3x4::CreateIdentity();
            AZ::Transform2RequestBus::EventResult(exact, entityId, &AZ::Transform2Requests::GetWorldMatrix);
            transform2 = MatrixJson(exact);
        }
#endif

        const float localScale = local.GetUniformScale();
        const float worldScale = world.GetUniformScale();

        dump.m_records += AZStd::string::format(
            "%s\n{\"id\":\"%llu\",\"name\":%s,\"parent\":\"%llu\",\"prefab\":%s,"
            "\"world\":%s,\"worldScale\":%.9g,"
            "\"local\":{\"translation\":%s,\"rotation\":%s,\"scale\":%.9g},"
            "\"nonUniformScale\":%s,\"transform2World\":%s,\"mesh\":%s,\"colliders\":%s}",
            dump.m_entities == 0 ? "" : ",",
            static_cast<unsigned long long>(static_cast<AZ::u64>(entityId)), Quoted(entity->GetName()).c_str(),
            static_cast<unsigned long long>(static_cast<AZ::u64>(parentId)), PrefabJson(entityId).c_str(),
            MatrixJson(AZ::Matrix3x4::CreateFromTransform(world)).c_str(), static_cast<double>(worldScale),
            VectorJson(local.GetTranslation()).c_str(), QuaternionJson(local.GetRotation()).c_str(),
            static_cast<double>(localScale),
            nonUniform.c_str(), transform2.c_str(), MeshJson(dump, entityId).c_str(),
            CollidersJson(dump, entityId).c_str());
        ++dump.m_entities;
    }

    // =========================================================================
    // CONSOLE COMMAND
    // =========================================================================

    static void ParityDump(const AZ::ConsoleCommandContainer& arguments)
    {
        if (arguments.empty())
        {
            AZ_Error("ParityProbe", false, "parity_dump needs the output folder as its argument");
            return;
        }

        Dump dump;
        dump.m_folder = AZStd::string(arguments[0]);

        AZ::ComponentApplicationBus::Broadcast(
            &AZ::ComponentApplicationRequests::EnumerateEntities,
            [&dump](AZ::Entity* entity)
            {
                bool isEditorEntity = false;
                AzToolsFramework::EditorEntityContextRequestBus::BroadcastResult(
                    isEditorEntity, &AzToolsFramework::EditorEntityContextRequests::IsEditorEntity, entity->GetId());
                if (isEditorEntity)
                {
                    DumpEntity(dump, entity);
                }
            });

        const AZStd::string record = "{\"entities\":[" + dump.m_records + "\n]}\n";
        WriteFile(dump, "record.json", record.data(), record.size());

        // Written last: its presence says the record is complete.
        const AZStd::string done = AZStd::string::format(
            "{\"entities\":%d,\"meshes\":%d,\"meshesNotReady\":%d,\"shapes\":%d,\"models\":%zu,\"writeErrors\":%d}\n",
            dump.m_entities, dump.m_meshes, dump.m_meshesNotReady, dump.m_shapes, dump.m_modelsWritten.size(),
            dump.m_writeErrors);
        WriteFile(dump, "probe_done.json", done.data(), done.size());

        AZ_Printf("ParityProbe", "parity_dump: %d entities, %d meshes (%d not ready), %d shapes -> %s\n",
            dump.m_entities, dump.m_meshes, dump.m_meshesNotReady, dump.m_shapes, dump.m_folder.c_str());
    }

    AZ_CONSOLEFREEFUNC("parity_dump", ParityDump, AZ::ConsoleFunctorFlags::Null,
        "Write the parity probe record of every editor entity to the folder given as argument");
} // namespace ParityProbe
