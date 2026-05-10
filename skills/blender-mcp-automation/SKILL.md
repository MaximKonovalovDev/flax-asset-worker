---
name: blender-mcp-automation
description: Advanced 5-pillar architecture for driving the Bluepuff71 MCP proxy. Covers Parametric Specification, Procedural Mutation, LOD Chaining, QA Validation, and API Resilience.
---

# Blender MCP Super-Skills Architecture

This skill defines the operational standard for how Antigravity (and any AssetBoy sub-agents) interacts with the `blender` MCP server. You are no longer just "making a cube"; you are executing a production-grade 3D pipeline.

## AssetBoy Local Wiring
- AssetBoy now pins the project MCP entrypoint to `C:\SHARE\blenders\blender-mcp-0.1.6\blender_mcp_proxy.py`.
- Start the Blender MCP addon server inside Blender first. The local proxy expects the addon HTTP server at `http://127.0.0.1:9876/mcp`.
- The core AssetBoy runbook should prefer these real tools when possible: `execute_python`, `scene_get_hierarchy`, `viewport_screenshot_angles`, `unity_validate_mesh`, `unity_validate_rig`, `unity_export_fbx`, and `unity_export_textures`.
- Treat Blender as the mandatory middle layer for 3D cleanup, QA, screenshot capture, and export before packet registration.

Whenever you generate or modify assets using Blender MCP, you MUST implement the following **5 Core Super-Skills**:

## 1. Hybrid Base Generation & Kitbashing (Stage A & C)
Do not attempt to generate complex organic shapes or highly detailed hard-surface meshes using pure Python mathematical primitives or raw BMesh scripting; this yields sterile, amateur-looking results.
- **Foundation Models**: For unique complex assets, rely on foundation models (e.g., Trellis, Hunyuan3D via Colab) to generate the chaotic, high-density base `.glb`.
- **AI Kitbashing**: For large structures (like arenas, buildings), build or source modular "kits" (pillars, archways, wall segments). Use Python purely to *assemble* and *instance* these pre-existing high-quality kits into larger structures.

## 2. Procedural Refinement Layer via Geometry Nodes (Stage B)
Procedural generation must be driven by Geometry Nodes (GN), not raw Python loops.
- Use `mcp_blender_execute_python` to load noisy Trellis meshes or raw kitbashed assemblies and apply pre-built Geometry Node modifier trees.
- The GN tree handles non-destructive topological cleanup: Voxel Remeshing to fix non-manifold AI geometry, curvature-based edge loops, and normal transfer to recapture detail.
- Do not use BMesh Boolean modifiers for complex intersections unless absolutely unavoidable; rely on visual geometry node paramaterization.

## 3. LOD Chain Generation & Validation (CRITICAL)
Every production asset destined for the Flax Engine MUST have a Level-of-Detail (LOD) chain.
- **LOD0**: Full detail (e.g., 20,000 vertices).
- **LOD1**: 50% reduction (e.g., 10,000 vertices).
- **LOD2**: 85% reduction (e.g., 3,000 vertices).
- Use `mcp_blender_execute_python` with the Decimate modifier (Collapse/Planar modes based on surface type) to generate these chains automatically.
- Validate that LOD1 < LOD0 * 0.6 polygons.

## 4. Asset Quality Assurance (QA) & Validation Pipeline
Assume every export is broken until proven otherwise. Before exporting to the payload folder, run the following sequence:
- **`unity_validate_mesh`**: Ensure vertex counts stay under 65k (16-bit indices), n-gons are destroyed, and UVs exist.
- **Manifold Check**: Ensure there are no non-manifold edges inside Blender.
- **Scale Check**: Scale must be `[1, 1, 1]`.
- **Origin Check**: Origin must be at the bottom center of the bounding box.

## 5. Blender API Resilience & State Management
Blender's Python API can hang or crash on unoptimized operations (like massive boolean intersects).
- **Clear the Scene**: Always delete the default cube and lights at the start.
- **Checkpointing**: If running complex multi-step generations, save the intermediate `.blend` file using Python so you can recover if a complex operation fails.
- **Error Handling**: Monitor the output of your Python scripts. If an operation fails, propose a fallback (e.g., if a boolean operation fails due to non-manifold geometry, run a "merge by distance" cleanup first).

---

## The Ultimate Workflow
When asked to create an asset:
1. **Plan**: Define the target vert count and LOD structure.
2. **Execute**: Run Python/BMesh scripts to build the base.
3. **Validate visually**: Take a screenshot.
4. **Decimate**: Generate the LOD versions.
5. **QA**: Run `unity_validate_mesh`.
6. **Export**: Export via `unity_export_fbx` directly into the `FlaxAssetLibrary\publish\flax_intake\...\payload\` folder.
