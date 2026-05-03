using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Threading.Tasks;
using FlaxEngine;
using Newtonsoft.Json.Linq;

namespace FAW.Pipeline
{
    public class QuickImportLane : ILane
    {
        public string Id => "quick-import";
        public string Name => "Quick Import";
        public string Description => "Download → Validate → Import. Fastest path for simple assets.";
        public LaneStepType[] Steps => new[] { LaneStepType.Download, LaneStepType.Validate, LaneStepType.Import };

        public async Task<LaneResult> ExecuteAsync(LaneInput input)
        {
            var sw = Stopwatch.StartNew();
            var result = new LaneResult { StepsCompleted = 0 };

            try
            {
                // Step 1: Download
                var provider = Providers.ProviderRegistry.Instance.GetProvider(input.ProviderId);
                if (provider == null)
                {
                    return new LaneResult { Success = false, Error = $"Provider '{input.ProviderId}' not found" };
                }

                var config = Providers.ProviderRegistry.Instance.GetConfig(input.ProviderId);
                var download = await provider.DownloadAsync(input.AssetId, config);
                if (!download.Success)
                {
                    result.Error = $"Download failed: {download.Error}";
                    return result;
                }
                result.StepsCompleted++;

                // Step 2: Validate
                var valid = await provider.ValidateAsync(download.LocalPath);
                if (!valid)
                {
                    result.Error = "Validation failed: file not found or corrupted";
                    result.StepsFailed++;
                    return result;
                }
                result.StepsCompleted++;

                // Step 3: Import (copy to project content folder)
                var outputDir = Path.Combine(Globals.ProjectFolder, input.OutputFolder ?? "Content/ImportedAssets");
                Directory.CreateDirectory(outputDir);
                var destFile = Path.Combine(outputDir, $"{input.AssetId}{Path.GetExtension(download.LocalPath)}");
                File.Copy(download.LocalPath, destFile, overwrite: true);

                result.StepsCompleted++;
                result.Success = true;
                result.OutputPath = destFile;
                result.DurationMs = sw.ElapsedMilliseconds;

                Debug.Log($"[AssetWorker] QuickImport complete: {input.AssetId} → {destFile} ({sw.ElapsedMilliseconds}ms)");
            }
            catch (Exception ex)
            {
                result.Error = ex.Message;
                result.StepsFailed++;
            }

            return result;
        }
    }

    public class LaneExecutor
    {
        private static readonly Dictionary<string, ILane> _lanes = new()
        {
            ["quick-import"] = new QuickImportLane()
        };

        public static List<ILane> GetAllLanes()
        {
            return new List<ILane>(_lanes.Values);
        }

        public static ILane GetLane(string id)
        {
            return _lanes.TryGetValue(id, out var lane) ? lane : null;
        }

        public static async Task<LaneResult> ExecuteAsync(string laneId, LaneInput input)
        {
            var lane = GetLane(laneId);
            if (lane == null)
                return new LaneResult { Success = false, Error = $"Lane '{laneId}' not found" };

            return await lane.ExecuteAsync(input);
        }
    }
}
