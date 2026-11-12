# The translations of the Niri frontend (#300): the .qm catalogs, and the QML
# module that loads one for the locale (catalog.h says why Quickshell needs it).
#
#   cmake -S translations -B build -G Ninja -DBUILD_TESTING=ON
#   cmake --build build && ctest --test-dir build --output-on-failure
#
# The Flatpak builds and installs this with prefix /app:
#   lib/tuna-installer-niri/qml/TunaInstaller/Translations   the QML module
#   share/tuna-installer-niri/translations                    the .qm files
# and the launcher puts the first on QML_IMPORT_PATH.
cmake_minimum_required(VERSION 3.22)
project(tuna-installer-niri-translations VERSION 0.1.0 LANGUAGES CXX)

include(CTest)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(Qt6 6.5 REQUIRED COMPONENTS Core Qml LinguistTools)
qt_standard_project_setup(REQUIRES 6.5)

set(TUNA_QML_INSTALL_DIR lib/tuna-installer-niri/qml/TunaInstaller/Translations)
set(TUNA_QM_INSTALL_DIR share/tuna-installer-niri/translations)

# --- the .qm files --------------------------------------------------------------
# Each ../i18n/tuna-installer-niri_<lang>.ts (shared/i18n/catalogs.py writes
# them). The template, ../i18n/tuna-installer-niri.ts, has no language and is
# not compiled. lrelease runs directly: qt_add_lrelease() changed its
# signature in Qt 6.7.
set(TUNA_QM_DIR "${CMAKE_BINARY_DIR}/translations")
file(GLOB TUNA_TS_FILES CONFIGURE_DEPENDS
    "${CMAKE_CURRENT_SOURCE_DIR}/../i18n/tuna-installer-niri_*.ts")
if(NOT TUNA_TS_FILES)
    message(FATAL_ERROR "No i18n/tuna-installer-niri_<lang>.ts to compile.")
endif()
set(TUNA_QM_FILES)
foreach(ts ${TUNA_TS_FILES})
    get_filename_component(name "${ts}" NAME_WE)
    set(qm "${TUNA_QM_DIR}/${name}.qm")
    add_custom_command(OUTPUT "${qm}"
        COMMAND ${CMAKE_COMMAND} -E make_directory "${TUNA_QM_DIR}"
        COMMAND Qt6::lrelease -silent "${ts}" -qm "${qm}"
        DEPENDS "${ts}"
        VERBATIM)
    list(APPEND TUNA_QM_FILES "${qm}")
endforeach()
add_custom_target(tuna-installer-niri-catalogs ALL DEPENDS ${TUNA_QM_FILES})
install(FILES ${TUNA_QM_FILES} DESTINATION ${TUNA_QM_INSTALL_DIR})

# --- the QML module TunaInstaller.Translations -----------------------------------
# One target that is its own plugin, loaded by the QML engine at run time.
qt_add_qml_module(tunatranslations
    URI TunaInstaller.Translations
    VERSION 1.0
    PLUGIN_TARGET tunatranslations
    OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/qml/TunaInstaller/Translations
    SOURCES catalog.cpp catalog.h
)
target_link_libraries(tunatranslations PRIVATE Qt6::Core Qt6::Qml)

install(TARGETS tunatranslations
    LIBRARY DESTINATION ${TUNA_QML_INSTALL_DIR}
    RUNTIME DESTINATION ${TUNA_QML_INSTALL_DIR})
install(FILES
    ${CMAKE_BINARY_DIR}/qml/TunaInstaller/Translations/qmldir
    ${CMAKE_BINARY_DIR}/qml/TunaInstaller/Translations/tunatranslations.qmltypes
    DESTINATION ${TUNA_QML_INSTALL_DIR})

if(BUILD_TESTING)
    find_package(Qt6 6.5 REQUIRED COMPONENTS Test)
    qt_add_executable(test_catalog tests/test_catalog.cpp)
    target_link_libraries(test_catalog PRIVATE Qt6::Core Qt6::Qml Qt6::Test)
    target_compile_definitions(test_catalog PRIVATE
        QML_BUILD_DIR="${CMAKE_BINARY_DIR}/qml"
        TUNA_QM_DIR="${TUNA_QM_DIR}"
        NIRI_UI_DIR="${CMAKE_CURRENT_SOURCE_DIR}/../ui")
    add_dependencies(test_catalog tunatranslations tuna-installer-niri-catalogs)
    add_test(NAME test_catalog COMMAND test_catalog)
endif()
