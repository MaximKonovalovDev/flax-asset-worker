using System;
using System.IO;
using System.Threading.Tasks;
using FlaxEngine;
using Newtonsoft.Json.Linq;

namespace FAW.Routes
{
    /// <summary>
    /// REST routes for canary smoke-test status (Path B v1.5 server-side).
    ///
    /// The Python canary writes `state/canary/canary_status.json` per run.
    /// This route just exposes it as HTTP so the flax-mcp facade can poll
    /// external-API health without invoking the Python CLI.
    ///
    /// Endpoint:
    ///   GET /api/v1/canary/status
    ///       Returns the canary_status.json contents verbatim, plus a
    ///       `success` field. Returns `success=false, error=no_canary_run`
    ///       when the file doesn't exist yet (canary never run on this box).
    /// </summary>
    public static class CanaryRoutes
    {
        public static Task<JObject> HandleStatusAsync()
        {
            try
            {
                // The Python sidecar writes to <repo_root>/state/canary/canary_status.json
                // where repo_root resolves via assetboy.library.paths.assetboy_root().
                // We mirror that lookup here: walk up from this assembly's location
                // until we find a Python/assetboy folder, then that's the repo root.
                var canaryPath = ResolveCanaryStatusPath();
                if (canaryPath == null || !File.Exists(canaryPath))
                {
                    return Task.FromResult(new JObject
                    {
                        ["success"] = false,
                        ["error"] = "no_canary_run",
                        ["note"] = "Run `python -m assetboy.canary` to generate state/canary/canary_status.json",
                        ["expected_path"] = canaryPath ?? "<unresolved>",
                    });
                }
                var text = File.ReadAllText(canaryPath);
                var parsed = JObject.Parse(text);
                parsed["success"] = true;
                parsed["path"] = canaryPath;
                return Task.FromResult(parsed);
            }
            catch (Exception ex)
            {
                return Task.FromResult(new JObject
                {
                    ["success"] = false,
                    ["error"] = $"canary_status_read_failed: {ex.Message}",
                });
            }
        }

        private static string ResolveCanaryStatusPath()
        {
            // Walk up from Globals.ProjectFolder looking for the canary state dir.
            // Standalone FAW layout: <repo>/state/canary/canary_status.json
            // Submodule layout:      <flax_repo>/external/flax-asset-worker/state/canary/...
            // Try both relative to the running project folder.
            var candidates = new[]
            {
                // Standalone
                Path.Combine(Globals.ProjectFolder, "state", "canary", "canary_status.json"),
                // Common submodule location
                Path.Combine(Globals.ProjectFolder, "external", "flax-asset-worker", "state",
                             "canary", "canary_status.json"),
                // If running inside flax-mcp's plugin dir
                Path.Combine(Globals.ProjectFolder, "..", "..", "..", "..", "flax-asset-worker",
                             "state", "canary", "canary_status.json"),
            };

            foreach (var c in candidates)
            {
                try
                {
                    var resolved = Path.GetFullPath(c);
                    if (File.Exists(resolved)) return resolved;
                }
                catch { /* skip */ }
            }
            // Return the first candidate as the "expected" path even when missing
            // — gives operator a clear hint of where the file should land.
            return candidates[0];
        }
    }
}
