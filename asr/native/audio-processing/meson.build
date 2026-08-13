project(
  'amphion-audio-processing',
  ['c', 'cpp'],
  version: '1.0.0',
  meson_version: '>=0.63',
  default_options: ['buildtype=release', 'c_std=c11', 'cpp_std=c++17'],
)

webrtc_project = subproject(
  'webrtc-audio-processing',
  default_options: ['default_library=static', 'gnustl=disabled'],
)
webrtc_audio_processing = webrtc_project.get_variable('audio_processing_dep')

native_sources = ['src/amphion_audio_processing.cpp']
native_cpp_args = []
native_link_args = []
if host_machine.system() == 'android'
  native_cpp_args += ['-DAMPHION_ANDROID_JNI=1']
  # The AAR must be self-contained; do not add an undeclared libc++_shared.so runtime dependency.
  native_link_args += ['-static-libstdc++']
endif

amphion_audio_processing = shared_library(
  'amphion_audio_processing',
  native_sources,
  dependencies: [webrtc_audio_processing],
  include_directories: include_directories('include'),
  cpp_args: native_cpp_args,
  link_args: native_link_args,
  install: true,
)

if not meson.is_cross_build()
  native_test = executable(
    'amphion_audio_processing_test',
    'tests/amphion_audio_processing_test.cpp',
    link_with: amphion_audio_processing,
    include_directories: include_directories('include'),
  )
  test('amphion_audio_processing', native_test)
endif
