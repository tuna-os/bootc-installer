pkgdatadir = join_paths(get_option('prefix'), get_option('datadir'), meson.project_name())
layoutsdir = join_paths(pkgdatadir, 'bootc_installer/layouts')

sources = [
  '__init__.py',
  'yes_no.py',
]

install_data(sources, install_dir: layoutsdir)
