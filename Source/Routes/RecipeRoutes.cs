using System;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Text;
using System.Threading.Tasks;
using FlaxEngine;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace FAW.Routes
{
    /// <summary>
    /// REST routes for YAML-driven recipe runs (Path B v1.5 server-side).
    ///
    /// Bridges HTTP clients (e.g. the flax-mcp monorepo facade) to the
    /// Typer CLI's pack sub-app via subprocess. The CLI emits JSON via
    /// --json so we parse the result and return it.
    ///
    /// Endpoints:
    ///   POST /api/v1/recipes/list
    ///        Returns: { recipes: [{game, recipe_id, pack_count, path}], count }
    ///        Calls: python -m assetboy.cli pack list-recipes --json
    ///
    ///   POST /api/v1/recipes/run
    ///        Body: { recipe_path, dry_run, resume, skip[], only_required }
    ///        Returns: { recipe_id, game, total_packs, completed, failed,
    ///                   required_failed, results: [...] }
    ///        Calls: python -m assetboy.cli pack from-recipe <path> --json
    ///
    ///   GET  /api/v1/packs/{pack_id}/status?game={game_scope}
    ///        Returns: full ledger dict
    ///        Calls: python -m assetboy.cli pack status <pack_id> --game <scope> --json
    /// </summary>
    public static class RecipeRoutes
    {
        public static async Task<JObject> HandleListAsync()
        {
            try
            {
                var output = await RunPackCliAsync(new[] { "pack", "list-recipes", "--json" });
                if (output.ExitCode != 0)
                {
                    return new JObject
                    {
                        ["success"] = false,
                        ["error"] = $"cli_exit_{output.ExitCode}",
                        ["stderr"] = output.Stderr,
                    };
                }
                var parsed = JObject.Parse(output.Stdout);
                parsed["success"] = true;
                return parsed;
            }
            catch (Exception ex)
            {
                return new JObject
                {
                    ["success"] = false,
                    ["error"] = $"recipes_list_failed: {ex.Message}",
                };
            }
        }

        public static async Task<JObject> HandleRunAsync(HttpListenerContext ctx)
        {
            try
            {
                JObject body;
                using (var reader = new StreamReader(ctx.Request.InputStream, ctx.Request.ContentEncoding))
                {
                    var json = await reader.ReadToEndAsync();
                    body = string.IsNullOrWhiteSpace(json) ? new JObject() : JObject.Parse(json);
                }

                var recipePath = (string)body["recipe_path"] ?? "";
                if (string.IsNullOrWhiteSpace(recipePath))
                {
                    return new JObject
                    {
                        ["success"] = false,
                        ["error"] = "missing_recipe_path",
                    };
                }
                var dryRun = (bool?)body["dry_run"] ?? false;
                var resume = (bool?)body["resume"] ?? true;
                var onlyRequired = (bool?)body["only_required"] ?? false;
                var skip = body["skip"] as JArray;

                var args = new System.Collections.Generic.List<string>
                {
                    "pack", "from-recipe", recipePath, "--json",
                };
                if (dryRun) args.Add("--dry-run");
                if (!resume) args.Add("--no-resume");  // resume is True by default
                if (onlyRequired) args.Add("--only-required");
                if (skip != null)
                {
                    foreach (var s in skip)
                    {
                        args.Add("--skip");
                        args.Add((string)s);
                    }
                }

                var output = await RunPackCliAsync(args.ToArray());
                // pack from-recipe exits non-zero when required packs fail, but that's
                // not a server error — return the JSON either way.
                var parsed = string.IsNullOrWhiteSpace(output.Stdout)
                    ? new JObject { ["error"] = "empty_stdout", ["stderr"] = output.Stderr }
                    : JObject.Parse(output.Stdout);
                parsed["success"] = output.ExitCode == 0;
                parsed["cli_exit_code"] = output.ExitCode;
                return parsed;
            }
            catch (Exception ex)
            {
                return new JObject
                {
                    ["success"] = false,
                    ["error"] = $"recipes_run_failed: {ex.Message}",
                };
            }
        }

        public static async Task<JObject> HandlePackStatusAsync(string packId, string gameScope)
        {
            if (string.IsNullOrWhiteSpace(packId))
            {
                return new JObject { ["success"] = false, ["error"] = "missing_pack_id" };
            }
            if (string.IsNullOrWhiteSpace(gameScope)) gameScope = "primitive_tech";
            try
            {
                var output = await RunPackCliAsync(new[]
                {
                    "pack", "status", packId, "--game", gameScope, "--json",
                });
                if (output.ExitCode != 0)
                {
                    return new JObject
                    {
                        ["success"] = false,
                        ["error"] = $"cli_exit_{output.ExitCode}",
                        ["stderr"] = output.Stderr,
                        ["pack_id"] = packId,
                    };
                }
                var parsed = JObject.Parse(output.Stdout);
                parsed["success"] = true;
                return parsed;
            }
            catch (Exception ex)
            {
                return new JObject
                {
                    ["success"] = false,
                    ["error"] = $"pack_status_failed: {ex.Message}",
                    ["pack_id"] = packId,
                };
            }
        }

        // ----------------------------------------------------------------- //
        // Subprocess helper
        // ----------------------------------------------------------------- //

        private struct CliOutput
        {
            public int ExitCode;
            public string Stdout;
            public string Stderr;
        }

        private static async Task<CliOutput> RunPackCliAsync(string[] args)
        {
            // Locate the standalone repo's Python dir relative to the running plugin.
            // PythonWorkerClient already does similar; reuse its strategy.
            var psi = new ProcessStartInfo
            {
                FileName = "python",
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                UseShellExecute = false,
                CreateNoWindow = true,
                WorkingDirectory = Globals.ProjectFolder,
            };
            psi.ArgumentList.Add("-m");
            psi.ArgumentList.Add("assetboy.cli");
            foreach (var a in args) psi.ArgumentList.Add(a);

            using var proc = new Process { StartInfo = psi };
            proc.Start();
            var stdoutTask = proc.StandardOutput.ReadToEndAsync();
            var stderrTask = proc.StandardError.ReadToEndAsync();
            await Task.Run(() => proc.WaitForExit(60_000));
            return new CliOutput
            {
                ExitCode = proc.ExitCode,
                Stdout = await stdoutTask,
                Stderr = await stderrTask,
            };
        }
    }
}
