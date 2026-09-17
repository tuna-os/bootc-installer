#include "diskmodel.h"

#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QProcess>
#include <QDebug>

DiskModel::DiskModel(QObject *parent)
    : QAbstractListModel(parent)
{
}

int DiskModel::rowCount(const QModelIndex &parent) const
{
    return parent.isValid() ? 0 : m_disks.size();
}

QVariant DiskModel::data(const QModelIndex &index, int role) const
{
    if (!index.isValid() || index.row() < 0 || index.row() >= m_disks.size())
        return {};
    const DiskEntry &d = m_disks.at(index.row());
    switch (role) {
    case DeviceRole:
        return d.device;
    case SizeRole:
        return d.size;
    case ModelRole:
        return d.model;
    case TransportRole:
        return d.transport;
    case SubtitleRole: {
        QStringList bits;
        if (!d.size.isEmpty())
            bits << d.size;
        if (!d.model.isEmpty())
            bits << d.model;
        if (!d.transport.isEmpty())
            bits << d.transport;
        return bits.join(QStringLiteral(" • "));
    }
    default:
        return {};
    }
}

QHash<int, QByteArray> DiskModel::roleNames() const
{
    return {
        {DeviceRole, "device"},
        {SizeRole, "size"},
        {ModelRole, "model"},
        {TransportRole, "transport"},
        {SubtitleRole, "subtitle"},
    };
}

QString DiskModel::deviceAt(int row) const
{
    if (row < 0 || row >= m_disks.size())
        return {};
    return m_disks.at(row).device;
}

void DiskModel::refresh()
{
    QByteArray raw;

    // Screenshot/test seam: point this at a file holding `lsblk -J` output and
    // no process is run. The capture harness uses it so the disk step
    // photographs a realistic machine instead of whatever a CI container
    // happens to expose. Never consulted unless the variable is set.
    const QString fake = qEnvironmentVariable("TUNA_INSTALLER_FAKE_LSBLK");
    if (!fake.isEmpty()) {
        QFile f(fake);
        if (f.open(QIODevice::ReadOnly))
            raw = f.readAll();
        else
            qWarning() << "TUNA_INSTALLER_FAKE_LSBLK set but unreadable:" << fake;
    } else {
        QProcess proc;
        proc.start(QStringLiteral("lsblk"),
               {QStringLiteral("-J"), QStringLiteral("-o"),
                    QStringLiteral("NAME,SIZE,TYPE,MODEL,TRAN")});
        proc.waitForFinished(5000);
        raw = proc.readAllStandardOutput();
    }

    QJsonParseError err;
    const auto doc = QJsonDocument::fromJson(raw, &err);
    QList<DiskEntry> found;
    if (err.error != QJsonParseError::NoError) {
        qWarning() << "Failed to parse lsblk output:" << err.errorString();
    } else {
        const auto devices = doc.object()[QLatin1String("blockdevices")].toArray();
        for (const auto &value : devices) {
            const QJsonObject obj = value.toObject();
            if (obj[QLatin1String("type")].toString() != QLatin1String("disk"))
                continue;
            DiskEntry e;
            e.device = QStringLiteral("/dev/") + obj[QLatin1String("name")].toString();
            e.size = obj[QLatin1String("size")].toString();
            e.model = obj[QLatin1String("model")].toString();
            const QString tran = obj[QLatin1String("tran")].toString();
            if (tran == QLatin1String("nvme"))
                e.transport = QStringLiteral("NVMe");
            else if (tran == QLatin1String("sata") || tran == QLatin1String("ata"))
                e.transport = QStringLiteral("SATA");
            else
                e.transport = tran.toUpper();
            found.append(e);
        }
    }

    beginResetModel();
    m_disks = found;
    endResetModel();
    Q_EMIT countChanged();
}
