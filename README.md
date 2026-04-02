# Neocron 2 HD Textures

AI-upscaled texture pack for Neocron 2, created using [Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN) 4x upscaling.

## Overview

All game textures have been upscaled to 4x their original resolution using the Real-ESRGAN neural network, producing sharp, clean textures while preserving the original cyberpunk art style.

### What's included

| Category | Description | Count |
|----------|-------------|-------|
| `gfx/decals/` | Wall decals, signs, graffiti, blood, dirt | ~200 |
| `gfx/modeltextures/` | Character skins, NPC textures, clothing | ~400 |
| `gfx/items/` | Weapons, armor, equipment icons | ~150 |
| `gfx/maps/` | World textures, floors, walls, ceilings | ~300 |
| `gfx/misc/` | Particles, effects, UI elements | ~50 |
| `gfx/rpos/` | RPOS (in-game UI) interface textures | ~100 |
| `gfx/rposv3/` | RPOS v3 updated interface | ~80 |
| `gfx/sky/` | Skybox textures | ~20 |
| `gfx/eventtextures/` | Event-specific textures | ~30 |
| `gfx/mainmenu/` | Main menu backgrounds and UI | ~20 |
| `gfx/weapon_fx/` | Weapon effect textures | ~50 |

## Installation

### Via Neocron Launcher (recommended)

1. Open **Settings** > **Addons** tab
2. Paste this repo URL: `https://github.com/igwtech/nc2-hd-textures`
3. Click **Install**
4. The launcher backs up your original textures and installs the HD versions

### Manual Installation

1. Download or clone this repo
2. Copy the `gfx/` directory into your Neocron 2 install directory (e.g., `~/Neocron2/`)
3. Overwrite existing files when prompted

## Uninstallation

### Via Launcher

Settings > Addons > click the **x** on "HD Textures" — original files are automatically restored from backup.

### Manual

Restore the original `gfx/` files from your game backup, or re-run the launcher's **UPDATE** to re-download originals from the CDN.

## Building from Source

The upscaling pipeline is in the [Neocron project tools](https://github.com/igwtech/Neocron-Launcher):

```bash
cd tools/

# Extract textures from PAK files
find ../files/gfx -name "pak_*.*" | while read f; do
  php -f pak_decompress.php "$f"
done

# Convert to PNG for upscaling
find tmp/ -name "*.dds" -o -name "*.bmp" | while read f; do
  convert "$f" "esrgan-input/$(basename $f).png"
done

# Upscale with Real-ESRGAN (4x, Vulkan GPU)
./realesrgan-ncnn-vulkan -v -i esrgan-input/ -o esrgan-output/

# Convert back to DDS/BMP and repack
# (see process.sh for full pipeline)
```

Requires:
- [Real-ESRGAN ncnn Vulkan](https://github.com/xinntao/Real-ESRGAN-ncnn-vulkan) — GPU-accelerated upscaler
- [ImageMagick](https://imagemagick.org/) — DDS/BMP conversion
- PHP CLI — PAK archive tools

## Credits

- Upscaling: [Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN) by Xintao Wang et al.
- Original textures: Reakktor Media GmbH
- Neocron Launcher: [igwtech/Neocron-Launcher](https://github.com/igwtech/Neocron-Launcher)

## License

This addon distributes modified versions of Neocron 2 game assets for use with the community server emulator. Original assets are copyright Reakktor Media GmbH.
