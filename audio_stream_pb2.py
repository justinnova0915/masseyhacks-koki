# -*- coding: utf-8 -*-
# Generated by the protocol buffer compiler.  DO NOT EDIT!
# NO CHECKED-IN PROTOBUF GENCODE
# source: audio_stream.proto
# Protobuf Python Version: 5.29.0
"""Generated protocol buffer code."""
from google.protobuf import descriptor as _descriptor
from google.protobuf import descriptor_pool as _descriptor_pool
from google.protobuf import runtime_version as _runtime_version
from google.protobuf import symbol_database as _symbol_database
from google.protobuf.internal import builder as _builder
_runtime_version.ValidateProtobufRuntimeVersion(
    _runtime_version.Domain.PUBLIC,
    5,
    29,
    0,
    '',
    'audio_stream.proto'
)
# @@protoc_insertion_point(imports)

_sym_db = _symbol_database.Default()




DESCRIPTOR = _descriptor_pool.Default().AddSerializedFile(b'\n\x12\x61udio_stream.proto\x12\x13kokoro_audio_stream\"b\n\nAudioChunk\x12\x12\n\naudio_data\x18\x01 \x01(\x0c\x12\x11\n\tstream_id\x18\x02 \x01(\t\x12\x14\n\x0ctimestamp_ms\x18\x03 \x01(\x03\x12\x17\n\x0fsequence_number\x18\x04 \x01(\x05\"\xbe\x01\n\rStreamSummary\x12\x39\n\x06status\x18\x01 \x01(\x0e\x32).kokoro_audio_stream.StreamSummary.Status\x12\x0f\n\x07message\x18\x02 \x01(\t\x12\x1d\n\x15total_chunks_received\x18\x03 \x01(\x05\"B\n\x06Status\x12\x0b\n\x07UNKNOWN\x10\x00\x12\x15\n\x11SUCCESS_PROCESSED\x10\x01\x12\x14\n\x10\x45RROR_PROCESSING\x10\x02\x32l\n\rAudioStreamer\x12[\n\x12ProcessAudioStream\x12\x1f.kokoro_audio_stream.AudioChunk\x1a\".kokoro_audio_stream.StreamSummary(\x01\x42\x03\x90\x01\x01\x62\x06proto3')

_globals = globals()
_builder.BuildMessageAndEnumDescriptors(DESCRIPTOR, _globals)
_builder.BuildTopDescriptorsAndMessages(DESCRIPTOR, 'audio_stream_pb2', _globals)
if not _descriptor._USE_C_DESCRIPTORS:
  _globals['DESCRIPTOR']._loaded_options = None
  _globals['DESCRIPTOR']._serialized_options = b'\220\001\001'
  _globals['_AUDIOCHUNK']._serialized_start=43
  _globals['_AUDIOCHUNK']._serialized_end=141
  _globals['_STREAMSUMMARY']._serialized_start=144
  _globals['_STREAMSUMMARY']._serialized_end=334
  _globals['_STREAMSUMMARY_STATUS']._serialized_start=268
  _globals['_STREAMSUMMARY_STATUS']._serialized_end=334
  _globals['_AUDIOSTREAMER']._serialized_start=336
  _globals['_AUDIOSTREAMER']._serialized_end=444
_builder.BuildServices(DESCRIPTOR, 'audio_stream_pb2', _globals)
# @@protoc_insertion_point(module_scope)
