using System.Net;
using System.Threading.Tasks;
using Newtonsoft.Json.Linq;

namespace FAW.Routes
{
    public static class LaneRoutes
    {
        public static JObject HandleList()
        {
            var lanes = new JArray
            {
                new JObject { ["id"] = "quick-import", ["name"] = "Quick Import", ["description"] = "Download → Validate → Import", ["steps"] = new JArray { "download", "validate", "import" } },
                new JObject { ["id"] = "full-pipeline", ["name"] = "Full Pipeline", ["description"] = "Download → Validate → Optimize → Convert → Import → Cleanup", ["steps"] = new JArray { "download", "validate", "optimize", "convert", "import", "cleanup" } },
                new JObject { ["id"] = "batch-process", ["name"] = "Batch Process", ["description"] = "Download multiple → Validate → Import all", ["steps"] = new JArray { "download", "validate", "import" } }
            };
            return new JObject { ["success"] = true, ["lanes"] = lanes, ["count"] = 3 };
        }

        public static Task<JObject> HandleExecuteAsync(string path, HttpListenerContext ctx)
        {
            var result = new JObject
            {
                ["success"] = false,
                ["error"] = "Lane execution not yet implemented. Use /api/v1/providers/{id}/download and import manually."
            };
            return Task.FromResult(result);
        }
    }
}
