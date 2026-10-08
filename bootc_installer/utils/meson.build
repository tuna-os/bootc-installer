pkgdatadir = join_paths(get_option('prefix'), get_option('datadir'), meson.project_name())
utilsdir = join_paths(pkgdatadir, 'bootc_installer/utils')

sources = [
  '__init__.py',
  'finals.py',
  'run_async.py',
  'processor.py',
  'recipe.py',
  'builder.py',
  'progress_parser.py',
  'codec_check.py',
  'phone_companion.py',
  'fisherman_runner.py',
  'fisherman_session.py',
  'branding.py',
  'copy.py',
  'sha512crypt.py',
]

install_data(sources, install_dir: utilsdir)
