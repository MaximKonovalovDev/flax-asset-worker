using System;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Threading.Tasks;
using FlaxEngine;
using Newtonsoft.Json.Linq;

namespace FAW.Routes
{
    /// <summary>
    /// Lane execution routes.
    ///
    /// Path B s10 (2026-05-10): inlined the QuickImport lane that previously
    /// lived in <c>Source/Pipeline/LaneExecutor.cs</c>. The <c>ILane</c>
    /// interface + <c>LaneExecutor</c> class were YAGNI — 100 lines of
    /// abstraction wrapping a single 50-line concrete lane, with no
    /// second-impl ever shipped. <c>Config/lanes.json</c> declared 3 lanes
    /// but only 1 had code (the other 2 returned "not yet implemented").
    /// Honest replacement: 1 inlined lane, no interface.
    ///
    /// When a real second lane materializes, re-introduce the abstraction.
    /// </summary>
    public static class LaneRoutes
    {
        public static JObject HandleList()
        {
            var lanes = new JArray
            {
                new JObject
                {
                    ["id"] = "quick-import",
                    ["name"] = "Quick Import",
                    ["description"] = "Download -> Validate -> Import",
                    ["steps"] = new JArray { "download", "validate", "import" },
                    ["implemented"] = true
                }
            };
            return new JObject
            {
                ["success"] = true,
                ["lanes"] = lanes,
                ["count"] = 1,
                ["note"] = "Path B s10: ILane abstraction inlined. Only quick-import is implemented today."
            };
        }

        public static async Task<JObject> HandleExecuteAsync(string path, HttpListenerContext ctx)
        {
            // Parse {laneId} out of /api/v1/lanes/{laneId}/execute
            var segments = path.Trim('/').Split('/');
            if (segments.Length < 4)
            {
                return new JObject { ["success"] = false, ["error"] = "invalid_path" };
            }
            var laneId = segments[3];
            if (laneId != "quick-import")
            {
                return new JObject
                {
                    ["success"] = false,
                    ["error"] = $"unknown_lane: {laneId} (only 'quick-import' is implemented; see HandleList)"
                };
            }

            // Read JSON body
            JObject body;
            try
            {
                using var reader = new StreamReader(ctx.Request.InputStream, ctx.Request.ContentEncoding);
                var json = await reader.ReadToEndAsync();
                body = string.IsNullOrWhiteSpace(json) ? new JObject() : JObject.Parse(json);
            }
            catch (Exception ex)
            {
                return new JObject { ["success"] = false, ["error"] = $"body_parse_error: {ex.Message}" };
            }

            var providerId = (string)body["provider_id"] ?? (string)body["provider"];
            var assetId = (string)body["asset_id"] ?? (string)body["assetId"];
            var category = (string)body["category"];
            var outputFolder = (string)body["output_folder"] ?? "Content/ImportedAssets";

            if (string.IsNullOrWhiteSpace(providerId) || string.IsNullOrWhiteSpace(assetId))
            {
                return new JObject
                {
                    ["success"] = false,
                    ["error"] = "missing_required_fields: provider_id + asset_id"
                };
            }

            // QuickImport: Download -> Validate -> Import (copy into Content/)
            var sw = Stopwatch.StartNew();
            var result = new JObject
            {
                ["lane_id"] = "quick-import",
                ["provider_id"] = providerId,
                ["asset_id"] = assetId,
                ["category"] = category,
                ["steps_completed"] = 0,
                ["steps_failed"] = 0
            };

            try
            {
                var provider = Providers.ProviderRegistry.Instance.GetProvider(providerId);
                if (provider == null)
                {
                    result["success"] = false;
                    result["error"] = $"provider_not_found: {providerId}";
                    return result;
                }

                // Step 1: Download
                var config = Providers.ProviderRegistry.Instance.GetConfig(providerId);
                var download = await provider.DownloadAsync(assetId, config);
                if (!download.Success)
                {
                    result["success"] = false;
                    result["error"] = $"download_failed: {download.Error}";
                    result["steps_failed"] = 1;
                    return result;
                }
                result["steps_completed"] = 1;
                result["download_path"] = download.LocalPath;

                // Step 2: Validate
                var valid = await provider.ValidateAsync(download.LocalPath);
                if (!valid)
                {
                    result["success"] = false;
                    result["error"] = "validate_failed: file not found or corrupted";
                    result["steps_failed"] = 1;
                    return result;
                }
                result["steps_completed"] = 2;

                // Step 3: Import (copy to project content folder)
                var outputDir = Path.Combine(Globals.ProjectFolder, outputFolder);
                Directory.CreateDirectory(outputDir);
                var destFile = Path.Combine(outputDir, $"{assetId}{Path.GetExtension(download.LocalPath)}");
                File.Copy(download.LocalPath, destFile, overwrite: true);

                result["steps_completed"] = 3;
                result["success"] = true;
                result["output_path"] = destFile;
                result["duration_ms"] = sw.ElapsedMilliseconds;

                Debug.Log($"[AssetWorker] QuickImport complete: {assetId} -> {destFile} ({sw.ElapsedMilliseconds}ms)");
            }
            catch (Exception ex)
            {
                result["success"] = false;
                result["error"] = ex.Message;
                result["steps_failed"] = 1;
            }

            return result;
        }
    }
}
