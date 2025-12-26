import json
with open(r'C:\Users\santi\AppData\Roaming\Claude\claude_desktop_config.json') as f:
    data = json.load(f)
    print("JSON VALID")
    print(f"MCP Servers: {list(data['mcpServers'].keys())}")
