cmake_minimum_required(VERSION 3.15)
project(ai_editor_video_engine LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

if(NOT DEFINED FFMPEG_ROOT)
    set(FFMPEG_ROOT "C:/ffmpeg_win_dev" CACHE PATH "FFmpeg开发库根目录")
endif()

set(FFMPEG_INCLUDE_DIR "${FFMPEG_ROOT}/include")
set(FFMPEG_LIB_DIR "${FFMPEG_ROOT}/lib")

if(NOT EXISTS "${FFMPEG_INCLUDE_DIR}/libavcodec/avcodec.h")
    message(FATAL_ERROR "FFmpeg头文件未找到: ${FFMPEG_INCLUDE_DIR}\n请设置 FFMPEG_ROOT 为FFmpeg开发包路径")
endif()

find_package(pybind11 REQUIRED)

set(SOURCES video_engine.cpp pybind11_wrapper.cpp)
set(HEADERS video_engine.h)

pybind11_add_module(video_engine_cpp ${SOURCES} ${HEADERS})

target_include_directories(video_engine_cpp PRIVATE ${FFMPEG_INCLUDE_DIR} .)
target_link_directories(video_engine_cpp PRIVATE ${FFMPEG_LIB_DIR})

target_link_libraries(video_engine_cpp PRIVATE
    avcodec avformat avfilter avutil swscale swresample
)

if(MSVC)
    target_compile_options(video_engine_cpp PRIVATE /O2 /fp:fast)
    target_compile_definitions(video_engine_cpp PRIVATE _CRT_SECURE_NO_WARNINGS NOMINMAX)
else()
    target_compile_options(video_engine_cpp PRIVATE -O3 -ffast-math)
endif()

if(WIN32)
    target_link_libraries(video_engine_cpp PRIVATE ws2_32 secur32 bcrypt)
endif()
