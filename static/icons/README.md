# MCP Icons

This directory contains the DevOps Agent MCP server icons for the Anthropic MCP Registry.

## Required Files

- `mcp-icon-light.png` - 128x128 PNG for light mode displays
- `mcp-icon-dark.png` - 128x128 PNG for dark mode displays

## Icon Design Guidelines

The icons should follow the DevOps Agent branding:
- Primary color: `#ff6b35` (orange accent)
- Background: Dark terminal aesthetic matching the app UI
- Simple, recognizable symbol representing infrastructure/DevOps tools
- Clear visibility at 128x128 resolution

## CDN URLs

Once deployed, these icons will be available at:
- https://devopsagent.io/static/icons/mcp-icon-light.png
- https://devopsagent.io/static/icons/mcp-icon-dark.png

## Generating Icons

You can generate these icons from the DevOps Agent logo using:

```bash
# Using ImageMagick (requires installation)
convert logo.png -resize 128x128 mcp-icon-light.png
convert logo.png -resize 128x128 -brightness-contrast 0x-30 mcp-icon-dark.png
```

Or use an online converter like:
- https://convertio.co/png-converter/
- https://www.iloveimg.com/resize-image

## Registry Reference

These icons are referenced in `mcp/server.json`:

```json
{
  "icons": {
    "light": "https://devopsagent.io/static/icons/mcp-icon-light.png",
    "dark": "https://devopsagent.io/static/icons/mcp-icon-dark.png"
  }
}
```

Note: The icon files need to be created and uploaded to this directory before submitting to the Anthropic MCP Registry.
