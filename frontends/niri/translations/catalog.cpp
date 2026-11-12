#include "catalog.h"

#include <QCoreApplication>
#include <QLocale>
#include <QQmlContext>
#include <QQmlEngine>
#include <QTranslator>
#include <QUrl>

Catalog::Catalog(QObject *parent)
    : QObject(parent)
{
}

Catalog::~Catalog()
{
    unload();
}

QString Catalog::domain()
{
    return QStringLiteral("tuna-installer-niri");
}

QString Catalog::directory() const
{
    if (!m_directory.isEmpty())
        return m_directory;
    const QQmlContext *context = qmlContext(this);
    if (!context)
        return {};
    const QUrl dir = context->baseUrl().resolved(QUrl(QStringLiteral("../translations")));
    return dir.isLocalFile() ? dir.toLocalFile() : QString();
}

void Catalog::setDirectory(const QString &directory)
{
    if (directory == m_directory)
        return;
    m_directory = directory;
    emit directoryChanged();
    if (m_complete)
        load();
}

bool Catalog::loaded() const
{
    return m_translator != nullptr;
}

QString Catalog::file() const
{
    return m_translator ? m_translator->filePath() : QString();
}

void Catalog::componentComplete()
{
    m_complete = true;
    load();
}

void Catalog::unload()
{
    if (!m_translator)
        return;
    QCoreApplication::removeTranslator(m_translator);
    delete m_translator;
    m_translator = nullptr;
}

void Catalog::load()
{
    const bool was = loaded();
    unload();
    const QString dir = directory();
    auto *translator = new QTranslator;
    if (!dir.isEmpty() && translator->load(QLocale(), domain(), QStringLiteral("_"), dir)
        && QCoreApplication::installTranslator(translator)) {
        m_translator = translator;
    } else {
        delete translator;
    }
    if (QQmlEngine *engine = qmlEngine(this); engine && (was || loaded()))
        engine->retranslate();
    if (was || loaded())
        emit loadedChanged();
}
