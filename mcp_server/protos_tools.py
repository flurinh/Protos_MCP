# In Protos_MCP/mcp_server/protos_tools.py
from mcp.server.fastmcp import Context as ToolContext


def register_protos_tools(server_instance_mcp_attr):
    """
    Registers Protos-specific tools.
    :param server_instance_mcp_attr: The 'mcp' attribute of the BaseMCPServer instance.
    """
    @server_instance_mcp_attr.tool()
    def my_protos_specific_tool(ctx: ToolContext, arg1: str) -> str:
        protos_ctx_data = ctx.request_context.lifespan_context
        # Access ProtosContext data: protos_ctx_data.base_path, protos_ctx_data.data etc.
        return f"Protos tool executed with {arg1}. Base path: {protos_ctx_data.base_path if protos_ctx_data else 'N/A'}"

    @server_instance_mcp_attr.tool()
    def get_protos_data_keys(ctx: ToolContext) -> list:
        protos_ctx_data = ctx.request_context.lifespan_context
        if protos_ctx_data and hasattr(protos_ctx_data, 'data'):
            return list(protos_ctx_data.data.keys())
        return []

    print("Protos-specific tools registered.")
