---
name: apk-ui-update
description: Provides a comprehensive workflow for updating Android APK UI elements (App name, Logo, Icons, Text, Titles) in a decompiled project. This guide covers both native Android resources and Jetpack Compose Multiplatform assets.
---

# 🛠️ APK UI Update Skill (Decompiled Project)

This guide details the procedure for modifying UI elements in a reverse-engineered Android project. It addresses naming, branding, and content updates for both standard Android XML-based systems and modern Compose Multiplatform frameworks.

## 🚀 Quick Start Checklist

1. [ ] **Triage**: Identify resource locations (Native vs. Assets).
2. [ ] **Brand Update**: Replace Launcher icons and App Name.
3. [ ] **Internal UI**: Replace logos and icons used within the app.
4. [ ] **Text Content**: Update strings, titles, and localized text.
5. [ ] **Rebuild & Sign**: Compile changes and sign for installation.

---

## 1. 📂 Resource Triage

Before making changes, determine if the project was decompiled with resources decoded (`apktool d`) or kept raw (`apktool d -r`).

- **Decoded**: Look for `.xml` files in `res/values/` and `res/layout/`.
- **Raw**: Look for `resources.arsc` in the root and binary `.xml` files.
  > [!IMPORTANT]
  > If `res/values/` is missing, you must re-decompile the APK *without* the `-r` flag to edit text easily.

---

## 2. 🏷️ Updating App Name & Title

### Native Android (Standard)
The app name is typically defined in `strings.xml` and referenced by the `AndroidManifest.xml`.

- **File**: `res/values/strings.xml`
- **Action**: Find the string named `app_name`.
  ```xml
  <string name="app_name">New App Name</string>
  ```
- **Manifest**: Ensure `AndroidManifest.xml` references it:
  ```xml
  <application android:label="@string/app_name" ...>
  ```

### Compose Multiplatform Assets
If the app uses Compose Multiplatform (like this Claude APK), some strings might be in `assets/`.
- **Path**: `assets/composeResources/*/values/`
- **File**: `strings.commonMain.cvr` or similar.
- **Action**: Use a compatible editor or patch the string if it's in a custom format.

---

## 3. 🖼️ Changing App Icon & Logos

### Launcher Icons
The launcher icon usually exists in multiple resolutions within `res/mipmap-*` or `res/drawable-*`.

- **Target Files**:
  - `ic_launcher.png` (Regular icon)
  - `ic_launcher_round.png` (Round icon)
- **Action**: Replace all instances across `hdpi`, `xhdpi`, `xxhdpi`, etc., with your new images. Keep the dimensions consistent.

### Internal Logos
Search for branding elements within the `res/drawable` directory.
- **Identified Logos**:
  - `claude_logotype.xml`
  - `logo_anthropic.xml`
  - `logo_claude_horizontal.xml`
  - `logo_claude_splash.xml`
- **Action**: Replace the vector XML content or corresponding PNG files.
- **Identification**: If you are unsure which file corresponds to which UI element:
  1. Open `res/layout/*.xml` files.
  2. Search for `ImageView` or `Image` tags.
  3. Look for the `android:src` attribute to find the drawable name.

---

## 🎨 Logo Conversion & Formatting

To ensure your new logo looks and behaves exactly like the original (scaling correctly without distortion), follow these conversion steps:

### 1. PNG/JPEG to SVG (Vectorization)
Android UI elements (like `logo_anthropic.xml`) are usually **Vector Drawables**. If you only have a PNG, you must first convert it to SVG.
- **Tools**: Adobe Illustrator, Figma, or online tools like `vectorizer.ai`.
- **Tip**: Simplify the paths to keep the XML size small.

### 2. SVG to Android Vector Drawable (XML)
Android does NOT support standard SVG files directly. You must convert SVG to the Android `<vector>` format.
- **Tool (Offline)**: Use **Android Studio** -> Right-click `res/drawable` -> `New` -> `Vector Asset` -> `Local file (SVG, PSD)`.
- **Tool (Online)**: Use `svg2android` (shapeshifter.design).

### 3. Matching the Original's Structure (Critical)
Open the original logo file (e.g., `res/drawable/logo_anthropic.xml`) and note the following attributes in the `<vector>` tag:
- `android:width="24dp"`
- `android:height="24dp"`
- `android:viewportWidth="1024"`
- `android:viewportHeight="1024"`

**Action**: Manually edit your new XML file to match these exact values. This ensures the new logo fits into the existing UI layout without being cut off or appearing too small.

### 4. Handling Colors
Original logos might use theme attributes like `android:fillColor="?attr/colorOnSurface"`.
- **Action**: Check if the original uses a hardcoded hex color (e.g., `#FFFFFF`) or a theme reference. Copy this attribute to your new `<path>` tags to maintain theme-switching compatibility.

---

## 4. ✍️ Updating UI Text & Labels

### Global String Search
To find specific text displayed in the app:
1. Grep the `res/values/` directory for the current text.
2. If not found, grep the `assets/` directory (common in React Native or Compose).
3. Update the value in the corresponding XML or asset file.

### Hardcoded Text in Code (Smali)
Sometimes text is hardcoded directly in the logic rather than in `strings.xml`.
- **Action**: Search for `const-string` in the `smali/` folders.
- **Example**:
  ```smali
  const-string v0, "Old Hardcoded Title"
  ```
- **Update**: Replace the string literal directly in the `.smali` file.

---

## ➕ Adding New Icons & Assets

If you want to add a *new* asset that wasn't there before, follow these steps:

### 1. Place the File
Add your new image (e.g., `my_new_icon.png`) to `res/drawable-xxxhdpi/`.

### 2. Register the ID (The `public.xml` Hack)
In a decompiled project, you must manually assign a resource ID so the app can find it.
- **File**: `res/values/public.xml`
- **Action**: Add a new entry with a unique hex ID (increment the last used ID in the `drawable` type).
  ```xml
  <public type="drawable" name="my_new_icon" id="0x7f080xyz" />
  ```

### 3. Use the Asset
- **In Layouts**: Reference it as `@drawable/my_new_icon`.
- **In Smali**: Find the hex ID you assigned in `public.xml` and use it in code:
  ```smali
  const v1, 0x7f080xyz  # ID for my_new_icon
  invoke-virtual {p0, v1}, Landroid/widget/ImageView;->setImageResource(I)V
  ```

---

## 🛡️ Stability & Failure Prevention

To ensure the modified APK installs and runs correctly without crashes or "Not Responding" (ANR) errors, follow these critical safety rules:

### 1. 🔑 Signing Protocol (Fixes "App Not Installed")
*   **Always Sign**: Android will not install an unsigned APK. Use `apksigner` instead of legacy `jarsigner`.
*   **Signature Scheme**: Use at least V2 and V3 signing schemes. Some modern Android versions reject V1-only signatures.
*   **Clean Install**: Always uninstall the original app before installing the modified version to avoid signature conflicts.

### 2. ⚡ Zipalign (Fixes "App Not Responding" / ANR)
*   **Uncompressed Data**: Android expects data in the APK to be aligned. If it's not, the OS has to read everything into memory, causing massive lag or ANR.
*   **The Rule**: **Zipalign BEFORE signing.** If you zipalign after signing, the signature becomes invalid.

### 3. 🧩 Manifest Integrity (Fixes "Instant Crash")
*   **Component Paths**: If you change the package name, you MUST update all activity/service references in `AndroidManifest.xml`.
*   **Launcher Activity**: Never delete or rename the Activity marked with `android.intent.action.MAIN` and `android.intent.category.LAUNCHER` unless you know what you are doing.

### 4. 🖼️ Resource Consistency (Fixes "Resource Not Found" Crash)
*   **File Naming**: Do not use spaces or special characters in resource names (only `a-z`, `0-9`, and `_`).
*   **Image Dimensions**: When replacing icons, ensure the new images have the same (or proportional) dimensions as the originals to avoid layout-driven crashes.
*   **XML Syntax**: Use a linter to ensure any modified XML files (like `strings.xml`) are syntactically correct. A missing `</string>` tag will break the build.

### 5. 🧊 Multi-DEX & Hermes (Fixes "Class Not Found" Crash)
*   **Smali Limits**: If you add many new files, you might exceed the 64k method limit. Avoid adding unnecessary libraries.
*   **Hermes Version**: If patching Hermes bytecode, ensure the `hbctool` version matches the Hermes engine version found in `libhermes.so`.

---

## 5. 🏗️ Rebuild, Sign, and Install

After modifying the files, you must rebuild the APK and sign it.

### Step 1: Rebuild with Apktool
```powershell
apktool b <project_folder> -o modified_app.apk
```

### Step 2: Zipalign (Optimization)
```powershell
zipalign -v 4 modified_app.apk optimized_app.apk
```

### Step 3: Sign the APK
Use `apksigner` with a keystore (you can generate a temporary one if needed).
```powershell
apksigner sign --ks temp.keystore --out final_app.apk optimized_app.apk
```

### Step 4: Install
```powershell
adb install final_app.apk
```

---

## ⚠️ Known Challenges (Hermes/Compose)

- **Hermes Bytecode**: If the app is React Native with Hermes, UI text is inside `index.android.bundle` (Hermes bytecode). You need `hbctool` to decompile/recompile this bundle for deep text changes.
- **CVR Resources**: Compose Multiplatform `.cvr` files are specialized resource packs. If standard `strings.xml` changes don't reflect in the UI, these files are the likely target.

---

## 🛠️ Recommended Tools

| Task | Tool |
|------|------|
| Decompilation | `apktool`, `jadx` |
| Image Editing | Photoshop, GIMP, Figma |
| Resource Editing | `ArscEditor`, `Android Asset Studio` |
| JS/Hermes Patching | `hbctool` |
| Signing | `apksigner`, `keytool` |

render_diffs(file:///C:/Users/JISHNU%20PG/Music/Claude/apktool_hermes_decompiled/apk-ui-update-skill.artifact.md)
