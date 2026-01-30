"""
Core infrastructure for Protos MCP Server.
"""

from .exceptions import *
from .processor_factory import ProcessorFactory
from .protos_manager import ProtosManager
from .logging_config import get_logger, setup_logging, log_tool_call, log_server_event
from .rate_limiter import RateLimiter, RateLimitConfig, RateLimitResult, check_rate_limit
from .response import (
    DataType,
    DataSummary,
    LLMResponse,
    build_structure_summary,
    build_sequence_summary,
    build_sequence_dataset_summary,
    build_grn_table_summary,
    build_property_table_summary,
    build_embedding_summary,
    build_ligand_response,
    build_alignment_summary,
    truncate_list,
    check_payload_size,
    safe_response,
)

__all__ = [
    # Managers
    'ProcessorFactory',
    'ProtosManager',
    # Logging
    'get_logger',
    'setup_logging',
    'log_tool_call',
    'log_server_event',
    # Rate Limiting
    'RateLimiter',
    'RateLimitConfig',
    'RateLimitResult',
    'check_rate_limit',
    # Exceptions
    'ProtosMCPError',
    'ProcessorNotFoundError',
    'EntityNotFoundError',
    'DatasetNotFoundError',
    'InvalidInputError',
    'ProcessorInitializationError',
    'DataSerializationError',
    # LLM-safe response builders
    'DataType',
    'DataSummary',
    'LLMResponse',
    'build_structure_summary',
    'build_sequence_summary',
    'build_sequence_dataset_summary',
    'build_grn_table_summary',
    'build_property_table_summary',
    'build_embedding_summary',
    'build_ligand_response',
    'build_alignment_summary',
    'truncate_list',
    'check_payload_size',
    'safe_response',
]