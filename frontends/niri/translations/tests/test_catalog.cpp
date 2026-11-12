// The shipped catalog loads and translates (#300).
//
// The build compiles ../i18n/tuna-installer-niri_fr.ts to a .qm file and the
// TunaInstaller.Translations module. Each test lays them out the way the
// Flatpak installs them (ui/ next to translations/), creates the catalog with
// ui/i18n.js from the source tree the way installer.qml does, and reads a
// qsTr() binding of the "installer" context.

#include <QCoreApplication>
#include <QDir>
#include <QFile>
#include <QLocale>
#include <QQmlComponent>
#include <QQmlEngine>
#include <QScopedPointer>
#include <QTemporaryDir>
#include <QTest>

namespace {

// The way installer.qml creates its catalog (its Component.onCompleted).
const char *const kInstaller = R"(import QtQml
import "i18n.js" as I18n
QtObject {
    id: root
    property string back: qsTr("Back")
    property string untranslated: qsTr("Your account")
    property QtObject catalog: null
    Component.onCompleted: root.catalog = I18n.createCatalog(root, Qt.resolvedUrl("installer.qml"))
}
)";

bool copy(const QString &from, const QString &to)
{
    QFile::remove(to);
    return QFile::copy(from, to);
}

} // namespace

class CatalogTest : public QObject
{
    Q_OBJECT

private:
    // ui/ with i18n.js and the probe file; translations/ with the .qm
    // files when `withCatalogs`.
    QString layOut(const QTemporaryDir &dir, bool withCatalogs)
    {
        const QString ui = dir.filePath(QStringLiteral("ui"));
        QDir().mkpath(ui);
        if (!copy(QStringLiteral(NIRI_UI_DIR "/i18n.js"), ui + QStringLiteral("/i18n.js")))
            return {};
        QFile probe(ui + QStringLiteral("/installer.qml"));
        if (!probe.open(QIODevice::WriteOnly))
            return {};
        probe.write(kInstaller);
        probe.close();
        if (withCatalogs) {
            const QString qm = dir.filePath(QStringLiteral("translations"));
            QDir().mkpath(qm);
            const QDir built(QStringLiteral(TUNA_QM_DIR));
            for (const QString &name : built.entryList({QStringLiteral("*.qm")}, QDir::Files))
                copy(built.filePath(name), qm + QLatin1Char('/') + name);
        }
        return probe.fileName();
    }

    QObject *create(QQmlEngine &engine, const QString &file)
    {
        engine.addImportPath(QStringLiteral(QML_BUILD_DIR));
        QQmlComponent component(&engine, QUrl::fromLocalFile(file));
        QObject *object = component.create();
        if (!object)
            qWarning().noquote() << component.errorString();
        return object;
    }

private slots:
    void noModuleShowsEnglishAndStillLoads()
    {
        // The screenshot harness and the wasm preview: no module on the
        // import path. createCatalog() returns null and the wizard loads.
        // First of the tests: once an engine has loaded the module, its
        // types stay registered in the process.
        QLocale::setDefault(QLocale(QStringLiteral("fr_FR")));
        QTemporaryDir dir;
        const QString file = layOut(dir, true);
        QQmlEngine engine;
        QQmlComponent component(&engine, QUrl::fromLocalFile(file));
        QScopedPointer<QObject> root(component.create());
        QVERIFY2(root, qPrintable(component.errorString()));
        QVERIFY(!root->property("catalog").value<QObject *>());
        QCOMPARE(root->property("back").toString(), QStringLiteral("Back"));
    }

    void theFrenchCatalogIsBuilt()
    {
        QVERIFY(QFile::exists(QStringLiteral(TUNA_QM_DIR "/tuna-installer-niri_fr.qm")));
    }

    void theShippedCatalogLoadsAndTranslates()
    {
        QLocale::setDefault(QLocale(QStringLiteral("fr_FR")));
        QTemporaryDir dir;
        const QString file = layOut(dir, true);
        QVERIFY(!file.isEmpty());
        QQmlEngine engine;
        QScopedPointer<QObject> root(create(engine, file));
        QVERIFY(root);
        auto *catalog = root->property("catalog").value<QObject *>();
        QVERIFY2(catalog, "i18n.js did not create a Catalog");
        QVERIFY(catalog->property("loaded").toBool());
        QVERIFY(catalog->property("file").toString().endsWith(
            QStringLiteral("/translations/tuna-installer-niri_fr.qm")));
        // The binding was evaluated in English, then retranslated.
        QCOMPARE(root->property("back").toString(), QStringLiteral("Retour"));
        // A message the catalog leaves untranslated keeps its English text.
        QCOMPARE(root->property("untranslated").toString(), QStringLiteral("Your account"));
        // The translator goes when the Catalog goes.
        delete catalog;
        QCOMPARE(QCoreApplication::translate("installer", "Back"), QStringLiteral("Back"));
    }

    void aLocaleWithNoCatalogShowsEnglish()
    {
        QLocale::setDefault(QLocale(QStringLiteral("ja_JP")));
        QTemporaryDir dir;
        const QString file = layOut(dir, true);
        QQmlEngine engine;
        QScopedPointer<QObject> root(create(engine, file));
        QVERIFY(root);
        auto *catalog = root->property("catalog").value<QObject *>();
        QVERIFY(catalog);
        QVERIFY(!catalog->property("loaded").toBool());
        QCOMPARE(catalog->property("file").toString(), QString());
        QCOMPARE(root->property("back").toString(), QStringLiteral("Back"));
    }

    void noCatalogDirectoryShowsEnglish()
    {
        QLocale::setDefault(QLocale(QStringLiteral("fr_FR")));
        QTemporaryDir dir;
        const QString file = layOut(dir, false);
        QQmlEngine engine;
        QScopedPointer<QObject> root(create(engine, file));
        QVERIFY(root);
        QCOMPARE(root->property("back").toString(), QStringLiteral("Back"));
    }
};

QTEST_GUILESS_MAIN(CatalogTest)

#include "test_catalog.moc"
