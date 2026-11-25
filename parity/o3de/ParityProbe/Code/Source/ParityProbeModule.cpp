/*
 * =============================================================================
 * PARITY PROBE - EDITOR MODULE
 *
 * The module carries no component. Loading it registers the console command
 * of ParityProbe.cpp (the module macro links the gem's console functors).
 * =============================================================================
 */

#include <AzCore/Memory/SystemAllocator.h>
#include <AzCore/Module/Module.h>

namespace ParityProbe
{
    class ParityProbeEditorModule
        : public AZ::Module
    {
    public:
        AZ_RTTI(ParityProbeEditorModule, "{6D2E3B1A-5F0C-4E8B-9A47-2C1D8E7F4B93}", AZ::Module);
        AZ_CLASS_ALLOCATOR(ParityProbeEditorModule, AZ::SystemAllocator);

        ParityProbeEditorModule()
            : AZ::Module()
        {
        }
    };
} // namespace ParityProbe

#if defined(O3DE_GEM_NAME)
AZ_DECLARE_MODULE_CLASS(AZ_JOIN(Gem_, O3DE_GEM_NAME, _Editor), ParityProbe::ParityProbeEditorModule)
#else
AZ_DECLARE_MODULE_CLASS(Gem_ParityProbe_Editor, ParityProbe::ParityProbeEditorModule)
#endif
