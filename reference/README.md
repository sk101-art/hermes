# HERMES — Project Reference & Context Directory

This directory is the local context folder for HERMES.

## How it works
Place your local project directories inside this folder:

```text
reference/
  my-rag-engine/
      README.md
      requirements.txt
      architecture.md
  cuda-compiler-lab/
      CMakeLists.txt
      include/
      src/
```

HERMES will statically index your projects, extract technology profiles, languages, dependencies, frameworks, and architecture topics, and match new technical developments and verified claims directly against your project context.

## Privacy & Security Guarantee
- **100% Local & Offline**: All project files and profiles are processed locally on your machine.
- **Zero Cloud Uploads**: No code or metadata is sent to any external LLM, API, or cloud database.
- **Static Analysis Only**: Project code is never executed, built, or installed.
- **Sensitive File Exclusion**: `.env`, credentials, secret keys, build artifacts, and binaries are automatically ignored.
