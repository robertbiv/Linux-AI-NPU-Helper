# Building the Flatpak locally

This guide walks you through building and installing Linux AI NPU Assistant as a
[Flatpak](https://flatpak.org/) package on your own machine so you can run it
in a sandboxed environment without affecting your system Python installation.

---

## Prerequisites

Install the required build tools for your distribution:

=== "Ubuntu / Debian"

    ```bash
    sudo apt update
    sudo apt install flatpak flatpak-builder
    flatpak remote-add --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
    ```

=== "Fedora"

    ```bash
    sudo dnf install flatpak flatpak-builder
    flatpak remote-add --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
    ```

=== "Arch Linux"

    ```bash
    sudo pacman -S flatpak flatpak-builder
    flatpak remote-add --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
    ```

=== "openSUSE"

    ```bash
    sudo zypper install flatpak flatpak-builder
    flatpak remote-add --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
    ```

!!! tip
    A reboot (or at minimum a log-out and log-back-in) may be required after
    adding the Flathub remote so that Flatpak can find the base runtimes.

---

## Step 1 — Clone the repository

```bash
git clone https://github.com/robertbiv/Linux-AI-NPU-Assistant.git
cd Linux-AI-NPU-Assistant
```

---

## Step 2 — Install the base runtime and SDK

The Flatpak manifest targets the **GNOME Platform 46** runtime (ships Python
3.12 and PyQt5). Install it once:

```bash
flatpak install flathub org.gnome.Platform//46 org.gnome.Sdk//46
```

If you prefer the KDE runtime (slightly smaller for KDE users):

```bash
flatpak install flathub org.kde.Platform//6.6 org.kde.Sdk//6.6
```

---

## Step 3 — Build

```bash
flatpak-builder \
  --force-clean \
  --user \
  build-dir \
  packaging/io.github.robertbiv.LinuxAiNpuAssistant.yml
```

`--force-clean` removes any previous build artefacts.  
`--user` installs into your user Flatpak directory (no `sudo` required).

!!! note "Build time"
    The first build downloads Python dependencies and may take 5–15 minutes
    depending on your internet connection. Subsequent builds are much faster
    thanks to the ccache and pip download cache.

---

## Step 4 — Install locally

```bash
flatpak-builder \
  --user \
  --install \
  --force-clean \
  build-dir \
  packaging/io.github.robertbiv.LinuxAiNpuAssistant.yml
```

Or install the already-built directory without rebuilding:

```bash
flatpak build-export repo build-dir
flatpak --user remote-add --no-gpg-verify local-npu-assistant repo
flatpak --user install local-npu-assistant io.github.robertbiv.LinuxAiNpuAssistant
```

---

## Step 5 — Run

```bash
flatpak run io.github.robertbiv.LinuxAiNpuAssistant
```

The application data (settings, conversation history) is stored in:

```
~/.var/app/io.github.robertbiv.LinuxAiNpuAssistant/
```

---

## NPU passthrough inside Flatpak

For AMD Ryzen AI NPU access inside the sandbox you need to grant the app
access to the NPU device nodes:

```bash
flatpak override \
  --user \
  --device=all \
  io.github.robertbiv.LinuxAiNpuAssistant
```

!!! warning "Security note"
    `--device=all` grants access to **all** device nodes, including GPU and
    input devices. This is required for NPU passthrough until the XDG Portal
    for compute devices lands. Use `--device=dri` if you only need GPU
    (non-NPU) acceleration.

---

## Uninstall

```bash
flatpak --user uninstall io.github.robertbiv.LinuxAiNpuAssistant
```

To also remove user data:

```bash
rm -rf ~/.var/app/io.github.robertbiv.LinuxAiNpuAssistant
```

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `flatpak-builder: command not found` | Install `flatpak-builder` via your package manager |
| `error: runtime not found` | Run Step 2 to install the correct runtime/SDK |
| Build fails with pip errors | Check you have internet access; try `--rebuild-on-sdk-change` flag |
| NPU not detected inside sandbox | Grant `--device=all` as described above |
| App launches but no window appears | Ensure Wayland/X11 socket access: `flatpak override --user --socket=x11 ...` |
