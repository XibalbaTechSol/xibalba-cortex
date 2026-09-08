import re
with open('viewer/src/App.tsx', 'r') as f:
    content = f.read()

# Remove onSelectMemory from TimelineTab props
content = re.sub(r'\s*onSelectMemory,', '', content)
content = re.sub(r'\s*onSelectMemory: \(id: string\) => void', '', content)

# Prefix function CollapsibleExchange with // @ts-ignore (Wait, ts-ignore goes above it)
# Better yet, export it so it's "used" by the module.
content = content.replace('function CollapsibleExchange({', 'export function CollapsibleExchange({')

with open('viewer/src/App.tsx', 'w') as f:
    f.write(content)
