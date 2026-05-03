using System;
using System.IO;
using System.Net;
using System.Threading.Tasks;
using FlaxEngine;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace FAW.Routes
{
    public static class ProviderRoutes
    {
        public static Task<JObject> HandleListAsync()
        {
            var result = ProviderRegistry.Instance.ListProviders();
            result["success"] = true;
            return Task.FromResult(result);
        }

        public static async Task<JObject> HandleDownloadAsync(string path, HttpListenerContext ctx)
        {
            // Parse provider ID from path: /api/v1/providers/{id}/download
            var segments = path.Trim('/').Split('/');
            if (segments.Length < 5)
                return ErrorResult("Invalid path. Expected: /api/v1/providers/{id}/download");

            var providerId = segments[3];
            var provider = ProviderRegistry.Instance.GetProvider(providerId);
            if (provider == null)
                return ErrorResult($"Provider '{providerId}' not found");

            // Read request body
            var body = await new StreamReader(ctx.Request.InputStream).ReadToEndAsync();
            var req = JObject.Parse(body ?? "{}");
            var assetId = req["asset_id"]?.ToString();
            if (string.IsNullOrWhiteSpace(assetId))
                return ErrorResult("'asset_id' is required");

            var config = ProviderRegistry.Instance.GetConfig(providerId);
            var result = await provider.DownloadAsync(assetId, config);

            var response = result.ToJson();
            response["success"] = result.Success;
            response["provider"] = providerId;
            return response;
        }
        
        public static Task<JObject> HandleSearchAsync(string path, HttpListenerContext ctx)
        {
            throw new NotImplementedException("Provider search not yet implemented");
        }

        private static JObject ErrorResult(string error)
        {
            return new JObject { ["success"] = false, ["error"] = error };
        }
    }
}
