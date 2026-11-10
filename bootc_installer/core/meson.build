pkgdatadir = join_paths(get_option('prefix'), get_option('datadir'), meson.project_name())
coredir = join_paths(pkgdatadir, 'bootc_installer/core')

subdir('locales')

sources = [
  '__init__.py',
  'locale.py',
  'languages.py',
  'keymaps.py',
  'timezones.py',
  'disks.py',
  'system.py',
]

# The fisherman probe and validate readers, and the encryption choices they
# read, are in the bootc_shared package (shared/python/meson.build).
install_data(sources, install_dir: coredir)
