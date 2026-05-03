using System;
using System.IO;
using FlaxEngine;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace FAW.Core
{
    public class WorkerConfig
    {
        public int Port { get; set; } = 8790;
        public bool VerboseLogging { get; set; } = false;
        public string ContentRoot { get; set; }
        public string LibraryRoot { get; set; }
        public string CacheRoot { get; set; }

        public static WorkerConfig Load()
        {
            var cfg = new WorkerConfig();

            // Environment overrides
            if (int.TryParse(Environment.GetEnvironmentVariable("ASSET_WORKER_PORT"), out var port) && port > 0)
                cfg.Port = port;

            if (bool.TryParse(Environment.GetEnvironmentVariable("ASSET_WORKER_VERBOSE"), out var verbose))
                cfg.VerboseLogging = verbose;

            // Resolve content roots relative to project
            var projectFolder = Globals.ProjectFolder;
            cfg.ContentRoot = Path.Combine(projectFolder, "Content", "ImportedAssets");
            cfg.LibraryRoot = Path.Combine(projectFolder, "Library");
            cfg.CacheRoot = Path.Combine(Path.GetTempPath(), "FAWCache");

            // Ensure directories exist
            Directory.CreateDirectory(cfg.ContentRoot);
            Directory.CreateDirectory(cfg.LibraryRoot);
            Directory.CreateDirectory(cfg.CacheRoot);

            return cfg;
        }

        public static WorkerConfig LoadFromFile(string path)
        {
            if (!File.Exists(path))
                return Load();

            var json = File.ReadAllText(path);
            var cfg = JsonConvert.DeserializeObject<WorkerConfig>(json) ?? new WorkerConfig();
            return cfg;
        }
    }
}
