<!-- Copyright 2026 stickleetoto | Apache-2.0 for BIO CE annotations; upstream dependency licenses remain separate -->
# Third-party dependency license inventory

Inventory date: 2026-10-21
Resolution: fresh BIO CE optional `mcp` and test install, CPython 3.12.14, Windows x64
Package source: the configured Python package index used by the installer; its host was not retained in the lock files or this audit. The upstream links identify project repositories, not the download endpoint.

The entries below record license identifiers from installed distribution metadata or the license files in the installed artifacts. This is a dependency inventory, not a grant of rights for the dependencies. BIO CE candidate source files are licensed under Apache-2.0; each dependency retains its own license.

## Installed artifact check

The candidate fresh Windows environment installed all 36 applicable lock entries at their pinned versions and passed pip check. The final pre-public audit rechecked the 36 lock entries against this inventory and the installed environment: all names and versions matched, and each installed distribution included at least one LICENSE, COPYING, or NOTICE file. The `colorama` and `packaging` metadata did not declare a license expression; their installed files provide the license texts. The `packaging` distribution contains Apache-2.0 and BSD-2-Clause texts. `pywin32` includes 15 license/notice files, and the pinned `setuptools` build backend includes 21, including notices for bundled components. These dependencies are installed separately; no third-party package source, wheel, or binary is checked into the BIO CE repository.

The lock files pin versions, not artifact hashes, and do not select an index host. Before publishing a wheel, executable, or other bundled artifact, inspect the exact release artifacts and carry forward applicable license and attribution notices. The present source repository does not contain those installed packages.

| Distribution | Tested version | License identifier (metadata/artifact) | Upstream source |
|---|---:|---|---|
| annotated-types | 0.8.0 | MIT | [annotated-types](https://github.com/annotated-types/annotated-types) |
| anyio | 4.15.1 | MIT | [anyio](https://github.com/agronholm/anyio) |
| attrs | 26.1.0 | MIT | [attrs](https://github.com/python-attrs/attrs) |
| cffi | 2.1.1 | MIT-0 | [cffi](https://github.com/python-cffi/cffi) |
| click | 8.5.0 | BSD-3-Clause | [Click](https://github.com/pallets/click) |
| cryptography | 50.0.2 | Apache-2.0 OR BSD-3-Clause | [cryptography](https://github.com/pyca/cryptography) |
| h11 | 0.16.0 | MIT | [h11](https://github.com/python-hyper/h11) |
| httpcore2 | 2.15.1 | BSD-3-Clause | [httpcore2](https://github.com/pydantic/httpx2/tree/main/src/httpcore2) |
| httpx2 | 2.15.1 | BSD-3-Clause | [httpx2](https://github.com/pydantic/httpx2) |
| idna | 3.20 | BSD-3-Clause | [idna](https://github.com/kjd/idna) |
| jsonschema | 4.26.0 | MIT | [jsonschema](https://github.com/python-jsonschema/jsonschema) |
| jsonschema-specifications | 2025.9.1 | MIT | [jsonschema-specifications](https://github.com/python-jsonschema/jsonschema-specifications) |
| mcp | 2.3.0 | MIT | [official Python SDK](https://github.com/modelcontextprotocol/python-sdk) |
| mcp-types | 2.3.0 | MIT | [MCP project](https://github.com/modelcontextprotocol/python-sdk) |
| opentelemetry-api | 1.45.1 | Apache-2.0 | [OpenTelemetry Python](https://github.com/open-telemetry/opentelemetry-python) |
| pydantic | 2.14.1 | MIT | [Pydantic](https://github.com/pydantic/pydantic) |
| pydantic-core | 2.50.1 | MIT | [Pydantic Core](https://github.com/pydantic/pydantic/tree/main/pydantic-core) |
| pycparser | 3.11 | BSD-3-Clause | [pycparser](https://github.com/eliben/pycparser) |
| PyJWT | 2.15.1 | MIT | [PyJWT](https://github.com/jpadilla/pyjwt) |
| pywin32 | 312 | PSF | [pywin32](https://github.com/mhammond/pywin32) (Windows only) |
| python-multipart | 0.0.32 | Apache-2.0 | [python-multipart](https://github.com/Kludex/python-multipart) |
| referencing | 0.37.0 | MIT | [referencing](https://github.com/python-jsonschema/referencing) |
| rpds-py | 2026.9.1 | MIT | [rpds-py](https://github.com/crate-py/rpds) |
| sse-starlette | 3.5.0 | BSD-3-Clause | [sse-starlette](https://github.com/sysid/sse-starlette) |
| setuptools (build backend) | 84.0.0 | MIT | [setuptools](https://github.com/pypa/setuptools) |
| starlette | 1.9.0 | BSD-3-Clause | [Starlette](https://github.com/Kludex/starlette) |
| truststore | 0.10.5 | MIT | [truststore](https://github.com/sethmlarson/truststore) |
| typing-extensions | 4.16.0 | PSF-2.0 | [typing-extensions](https://github.com/python/typing_extensions) |
| typing-inspection | 0.4.4 | MIT | [typing-inspection](https://github.com/pydantic/typing-inspection) |
| uvicorn | 0.54.0 | BSD-3-Clause | [Uvicorn](https://github.com/Kludex/uvicorn) |

The tested install includes HTTP transport dependencies because they are required by the official SDK package, even though BIO CE starts only the stdio transport. No HTTP endpoint is started.

## Windows executable build toolchain

These tools are pinned in `requirements-build.lock.txt` and installed only into the developer virtual environment. The packaging tools themselves are not copied as Python packages into the app bundle; the PyInstaller bootloader is part of the generated executables. PyInstaller documents an exception that permits distributing output bundles without including its license file, subject to the bundled dependencies' licenses. The build records the resolved versions below.

| Distribution | Resolved version | License identifier | Use |
|---|---:|---|---|
| altgraph | 0.17.5 | MIT | PyInstaller build-time dependency |
| pefile | 2024.8.26 | MIT | PyInstaller build-time dependency |
| PyInstaller | 6.22.3 | GPL-2.0-or-later with PyInstaller exception; selected files also Apache-2.0 | Windows executable bootloader/build tool; see upstream `COPYING.txt` |
| pyinstaller-hooks-contrib | 2026.9 | Multiple; see installed `LICENSE` | Build-time hooks, not runtime package code |
| pywin32-ctypes | 0.2.3 | BSD-3-Clause | PyInstaller build-time dependency |
| packaging | 25.0 | Apache-2.0 OR BSD-2-Clause | Shared build/test dependency; absent from both PyInstaller app bundles and the runtime notice file |

The generated `THIRD_PARTY_NOTICES` file is copied into the installed app folder and is viewable from
**Settings → Third-party notices**. It contains, in this order: the license files of every locked runtime
distribution in `requirements-mcp.lock.txt` (including vendored packages inside `setuptools`); the CPython
`LICENSE.txt`, whose "Additional Conditions for this Windows binary build" cover the Microsoft Visual C++
runtime (`VCRUNTIME140*.dll`), bzip2, libffi, and Tcl/Tk/Tix; CPython's "Licenses and Acknowledgements for
Incorporated Software" for 3.12.10 (`packaging/notices/cpython-3.12.10-license.rst`, a verbatim copy of
`Doc/license.rst` at tag v3.12.10, pinned by SHA-256), which carries the OpenSSL 3 (Apache-2.0), expat, zlib,
and libmpdec notices; the Tcl/Tk `license.terms`; the PyInstaller `COPYING.txt` (bootloader exception); and
the Inno Setup license. SQLite and liblzma are public domain. The collector refuses to build with any other
CPython version until the matching `Doc/license.rst` is added.

Rust extension modules (`pydantic-core`, `rpds-py`, `cryptography`) statically link crates whose individual
licenses are represented only by those distributions' own license files; this is an upstream packaging
limitation that RC1 does not resolve.

### Runtime and installer components (v0.2.0-rc1)

| Component | Version | License | How it ships |
|---|---:|---|---|
| CPython (official python.org Windows x64 build, PSF-signed) | 3.12.10 | PSF-2.0 plus the Windows-build third-party conditions in its `LICENSE.txt` | Frozen into both executables |
| Tcl/Tk | 8.6 | Tcl/Tk license (BSD-style) | `_tcl_data`, `_tk_data`, `tcl86t.dll`, `tk86t.dll` in the GUI |
| Microsoft Visual C++ runtime | from the CPython 3.12.10 installer | Microsoft Distributable Code terms, as relayed by the CPython `LICENSE.txt` | `VCRUNTIME140.dll`, `VCRUNTIME140_1.dll` |
| PyInstaller bootloader | 6.22.3 | GPL-2.0-or-later with the PyInstaller bootloader exception | Embedded in `BIO-CE.exe` and `MCP\BIO-CE-MCP.exe` |
| Inno Setup | 6.7.3 | Inno Setup License (permissive; commercial use allowed) | Setup and uninstall programs (`unins000.exe`) |

The Universal C Runtime (`ucrtbase.dll`, `api-ms-win-*.dll`) is **not** bundled. Windows 10 and 11 ship
it as an operating-system component. Earlier v0.2 developer builds picked up app-local UCRT forwarder DLLs
from unrelated tools on the build machine's `PATH`; the build script now runs PyInstaller with a minimal
`PATH` and fails if any UCRT DLL appears in the bundle.

### Installer tool decision

The v0.2 developer preview used Windows IExpress. Microsoft does not publish separate redistribution terms
for IExpress-generated self-extractors, and the preview also needed PowerShell scripts run with
`-ExecutionPolicy Bypass`, had no real uninstaller, and wrote no version information. RC1 uses Inno Setup
6.7.3 instead. Its bundled `license.txt` grants permission "to use this software for any purpose, including
commercial applications", subject to keeping copyright notices and not misrepresenting the origin. Since
6.5.0 the authors also sell optional commercial licenses and *ask* commercial users to buy one; this is a
request, not a condition of the license text shipped with 6.7.3. The Inno Setup copyright notice stays intact
in the Setup and uninstaller version resources, and its license text is included in `THIRD_PARTY_NOTICES`.
The compiler used for RC1 carried a valid Authenticode signature from its publisher (verified by the build
script).

RC1 is not code-signed. No Windows SmartScreen reputation claim is made.

## Test-only dependencies

The repository also pins a test runner separately from the MCP runtime set. These packages are needed only to reproduce the local pytest command and are not BIO CE runtime dependencies.

| Distribution | Tested version | License | Source |
|---|---:|---|---|
| colorama (Windows only) | 0.4.6 | BSD-3-Clause (license file; metadata unspecified) | [colorama](https://github.com/tartley/colorama) |
| iniconfig | 2.3.0 | MIT | [iniconfig](https://github.com/pytest-dev/iniconfig) |
| packaging | 25.0 | Apache-2.0 OR BSD-2-Clause (license files; metadata unspecified) | [packaging](https://github.com/pypa/packaging) |
| pluggy | 1.6.0 | MIT | [pluggy](https://github.com/pytest-dev/pluggy) |
| Pygments | 2.20.0 | BSD-2-Clause | [Pygments](https://github.com/pygments/pygments) |
| pytest | 9.0.2 | MIT | [pytest](https://github.com/pytest-dev/pytest) |

`requirements-mcp.lock.txt` and `requirements-test.lock.txt` pin package versions but do not pin wheel hashes or an index host. Refresh and review both lock files when the tested dependency set changes.

## CI actions

The workflow uses GitHub-maintained actions and does not vendor their source into this repository.

| Action | Reference | License |
|---|---|---|
| actions/checkout | [`actions/checkout@v4`](https://github.com/actions/checkout/tree/v4) | [MIT](https://github.com/actions/checkout/blob/v4/LICENSE) |
| actions/setup-python | [`actions/setup-python@v5`](https://github.com/actions/setup-python/tree/v5) | [MIT](https://github.com/actions/setup-python/blob/v5/LICENSE) |
| actions/upload-artifact | [`actions/upload-artifact@v7`](https://github.com/actions/upload-artifact/tree/v7) | [MIT](https://github.com/actions/upload-artifact/blob/v7/LICENSE) |

The Windows-only workflow pins major action tags, not immutable commit SHAs. Pytest text and JUnit logs are uploaded for 14 days after a failed test step. Review and pin audited SHAs before treating CI as a supply-chain hardened release gate. The push-triggered run failed before a runner was assigned; no workflow step, including upload-artifact, executed. GitHub-hosted test execution remains unverified under the current Actions limit.
