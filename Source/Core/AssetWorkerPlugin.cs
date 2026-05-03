using FlaxEngine;

namespace FAW.Core
{
    public class AssetWorkerPlugin : GamePlugin
    {
        private WorkerHttpServer _server;

        public AssetWorkerPlugin()
        {
            _description = new PluginDescription
            {
                Name = "FAW",
                Version = new Version(1, 0, 0),
                Author = "Flax Game Factory",
                Description = "Modular asset pipeline with HTTP/JSON-RPC. Providers, lanes, library.",
                Category = "Pipeline",
                IsAlpha = false
            };
        }

        public override void InitializePlugin()
        {
            base.InitializePlugin();
            var config = WorkerConfig.Load();
            _server = new WorkerHttpServer(config);
            _server.Start();
            Debug.Log($"[AssetWorker] Started on port {config.Port}");
        }

        public override void DeinitializePlugin()
        {
            _server?.Stop();
            base.DeinitializePlugin();
        }
    }
}
