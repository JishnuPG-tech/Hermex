# Implementation Plan: UI Branding Update (Claude to Hermes)

This plan outlines the steps to replace the "Claude" branding with "Hermes" and update the "Anthropic" footer to "Apex" while ensuring APK stability.

## User Review Required

> [!IMPORTANT]
> **Manual Image Replacement**: I will save your provided logo as a PNG in the resource folders. To ensure high quality across all devices, I will place it in multiple `res/drawable-*` folders.
> **Font Matching**: Since "Claude" uses a custom serif font, I will use a standard serif path for "Hermes" unless you provide a specific SVG path.

## Proposed Changes

### 1. 🖼️ Logo Icon Replacement (The Star)
- **Files**:
  - [NEW] `res/drawable-xxxhdpi/brand_logo_custom.png` (Saving the provided image)
  - [MODIFY] `unknown/res/drawable/anthropicon_asterix.xml`
- **Action**: Replace the vector content of the star icon with a reference to the new PNG logo.

### 2. 🏷️ Title Update ("Claude" -> "Hermes")
- **Files**:
  - [MODIFY] `unknown/res/drawable/claude_logotype.xml`
  - [MODIFY] `unknown/res/drawable/logo_claude_horizontal.xml`
  - [MODIFY] `assets/composeResources/claude.agentchat.generated.resources/values/strings.commonMain.cvr`
- **Action**:
  - Replace the vector path data for the "Claude" wordmark with "Hermes".
  - Update all base64-encoded instances of "Claude" in the Compose resource pack to "Hermes".

### 3. 🦶 Footer Update ("BY ANTHROPIC" -> "BY APEX")
- **Files**:
  - [MODIFY] `unknown/res/drawable/logo_anthropic.xml`
  - [MODIFY] `assets/composeResources/claude.agentchat.generated.resources/values/strings.commonMain.cvr`
- **Action**: Update the branding footer to say "BY APEX".

### 4. 📦 Stability & Build
- **Action**:
  - Use `apktool b` to rebuild.
  - **Zipalign** the output APK.
  - **Sign** the APK using `apksigner` with the existing `temp.keystore`.

## Verification Plan

### Automated Checks
- Run `apktool b` and check for resource compilation errors.
- Validate that the modified `.cvr` file is still valid base64.

### Manual Verification
- Install the APK on a device.
- Verify the splash screen shows the new logo and "Hermes".
- Verify the footer shows "BY APEX".
- Ensure the app doesn't crash on launch (Resource consistency check).
