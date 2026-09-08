import re

with open('viewer/src/App.tsx', 'r') as f:
    content = f.read()

old_hero_start = '<section className="cortex-hero"><div className="cortex-hero-copy"><p className="cortex-kicker">'
new_hero_start = '<section className="cortex-hero"><div className="cortex-hero-copy"><img src="/CortexBWLogo.png" alt="Cortex Logo" className="cortex-hero-logo" /><p className="cortex-kicker">'
content = content.replace(old_hero_start, new_hero_start)

with open('viewer/src/App.tsx', 'w') as f:
    f.write(content)
