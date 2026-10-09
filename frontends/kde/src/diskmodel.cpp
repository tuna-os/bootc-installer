#include "diskmodel.h"

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
    const probe::Disk &d = m_disks.at(index.row());
    switch (role) {
    case DeviceRole:
        return d.path;
    case SizeRole:
        return d.sizeLabel;
    case ModelRole:
        return d.model;
    case TransportRole:
        return d.transportLabel;
    case TitleRole:
        return d.title;
    case RemovableRole:
        return d.removable;
    case SubtitleRole: {
        QStringList bits{d.path, d.sizeLabel};
        if (!d.transportLabel.isEmpty())
            bits << d.transportLabel;
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
        {TitleRole, "title"},
        {RemovableRole, "removable"},
    };
}

QString DiskModel::deviceAt(int row) const
{
    if (row < 0 || row >= m_disks.size())
        return {};
    return m_disks.at(row).path;
}

void DiskModel::refresh()
{
    setResult(probe::run());
}

void DiskModel::setResult(const probe::Result &result)
{
    beginResetModel();
    m_disks = result.disks;
    m_error = result.ok ? QString() : result.error;
    endResetModel();
    Q_EMIT countChanged();
}
