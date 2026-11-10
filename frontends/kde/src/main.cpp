#include <QApplication>
#include <QQmlApplicationEngine>
#include <QLocale>
#include <QQuickStyle>
#include <QStandardPaths>
#include <QTranslator>

#include "readiness.h"

using namespace Qt::StringLiterals;

int main(int argc, char *argv[])
{
    QApplication app(argc, argv);
    app.setApplicationName(u"TunaOS Installer"_s);
    app.setApplicationVersion(u"0.1.0"_s);
    app.setOrganizationName(u"tuna-os"_s);
    app.setDesktopFileName(u"org.tunaos.InstallerKde"_s);

    // Plasma's own Qt Quick Controls style. The Widgets frontend this replaces
    // forced Fusion, which never matched the desktop it shipped on.
    if (qEnvironmentVariableIsEmpty("QT_QUICK_CONTROLS_STYLE"))
        QQuickStyle::setStyle(u"org.kde.desktop"_s);

    // Every user-facing string goes through qsTr() or tr() (#300). No
    // catalog ships yet; one installed as
    // share/tuna-installer-kde/translations/tuna-installer-kde_<locale>.qm
    // is loaded here, before the QML is.
    QTranslator translator;
    const QString translations = QStandardPaths::locate(
        QStandardPaths::GenericDataLocation, u"tuna-installer-kde/translations"_s,
        QStandardPaths::LocateDirectory);
    if (!translations.isEmpty()
        && translator.load(QLocale(), u"tuna-installer-kde"_s, u"_"_s, translations))
        app.installTranslator(&translator);

    QQmlApplicationEngine engine;
    engine.loadFromModule("org.tunaos.installer"_L1, "Main"_L1);
    if (engine.rootObjects().isEmpty())
        return -1;

    // Record that a frame actually reached the compositor. installer-smoke.yml
    // proves this frontend is up with `flatpak ps` — "is the process alive",
    // which is a different question from "did the user get a window". They
    // have already diverged: the COSMIC leg ran the process with no window
    // ever appearing and the check stayed green. See readiness.h.
    readiness::armStamp(engine.rootObjects().constFirst());

    return app.exec();
}
