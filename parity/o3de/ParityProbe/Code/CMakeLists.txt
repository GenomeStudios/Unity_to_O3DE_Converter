# The probe exists only in the Editor: one tools module, no runtime part.
if(NOT PAL_TRAIT_BUILD_HOST_TOOLS)
    return()
endif()

ly_add_target(
    NAME ${gem_name}.Editor GEM_MODULE
    NAMESPACE Gem
    FILES_CMAKE
        parityprobe_editor_files.cmake
    INCLUDE_DIRECTORIES
        PRIVATE
            Source
    BUILD_DEPENDENCIES
        PRIVATE
            AZ::AzCore
            AZ::AzFramework
            AZ::AzToolsFramework
            Gem::Atom_RPI.Public
            Gem::AtomLyIntegration_CommonFeatures.Public
)

# The module macro needs the gem's name to form the module's entry symbol.
ly_add_source_properties(
    SOURCES
        Source/ParityProbeModule.cpp
    PROPERTY COMPILE_DEFINITIONS
        VALUES
            O3DE_GEM_NAME=${gem_name}
            O3DE_GEM_VERSION=${gem_version})

ly_create_alias(NAME ${gem_name}.Tools NAMESPACE Gem TARGETS Gem::${gem_name}.Editor)
