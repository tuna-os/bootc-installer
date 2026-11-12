#pragma once

#include <QObject>
#include <QQmlParserStatus>
#include <QtQml/qqmlregistration.h>

class QTranslator;

// Catalog loads the Qt catalog of the Niri frontend for the locale (#300).
//
// Quickshell runs ui/installer.qml in a plain QQmlEngine, which installs no
// translator, so qsTr() would show the English text forever. installer.qml
// creates one Catalog through ui/i18n.js. When the component is
// complete, Catalog loads <directory>/tuna-installer-niri_<lang>.qm for the
// locale's UI languages ("fr_FR", then "fr"), installs it in the
// application and retranslates the engine, so every qsTr() binding shows
// the translation.
//
// `directory` defaults to ../translations from the QML file that creates the
// Catalog: /app/share/tuna-installer-niri/translations in the Flatpak, where
// this directory's CMakeLists.txt installs the .qm files.
class Catalog : public QObject, public QQmlParserStatus
{
    Q_OBJECT
    Q_INTERFACES(QQmlParserStatus)
    QML_ELEMENT
    Q_PROPERTY(QString directory READ directory WRITE setDirectory NOTIFY directoryChanged)
    Q_PROPERTY(bool loaded READ loaded NOTIFY loadedChanged)
    Q_PROPERTY(QString file READ file NOTIFY loadedChanged)

public:
    explicit Catalog(QObject *parent = nullptr);
    ~Catalog() override;

    static QString domain();

    QString directory() const;
    void setDirectory(const QString &directory);
    bool loaded() const;
    // The .qm file that is installed, or "" when none is.
    QString file() const;

    void classBegin() override {}
    void componentComplete() override;

signals:
    void directoryChanged();
    void loadedChanged();

private:
    void load();
    void unload();

    QString m_directory;
    QTranslator *m_translator = nullptr;
    bool m_complete = false;
};
