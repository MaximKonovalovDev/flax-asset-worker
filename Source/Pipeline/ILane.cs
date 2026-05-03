using System.Threading.Tasks;
using Newtonsoft.Json.Linq;

namespace FAW.Pipeline
{
    public enum LaneStepType
    {
        Download,
        Validate,
        Optimize,
        Convert,
        Import,
        Cleanup
    }

    public class LaneInput
    {
        public string AssetId { get; set; }
        public string ProviderId { get; set; }
        public string Category { get; set; }
        public string OutputFolder { get; set; }
        public string LocalPath { get; set; }
        public JObject Metadata { get; set; }
    }

    public class LaneResult
    {
        public bool Success { get; set; }
        public string OutputPath { get; set; }
        public string Error { get; set; }
        public long DurationMs { get; set; }
        public int StepsCompleted { get; set; }
        public int StepsFailed { get; set; }

        public JObject ToJson()
        {
            return new JObject
            {
                ["success"] = Success,
                ["output_path"] = OutputPath,
                ["error"] = Error,
                ["duration_ms"] = DurationMs,
                ["steps_completed"] = StepsCompleted,
                ["steps_failed"] = StepsFailed
            };
        }
    }

    public interface ILane
    {
        string Id { get; }
        string Name { get; }
        string Description { get; }
        LaneStepType[] Steps { get; }

        Task<LaneResult> ExecuteAsync(LaneInput input);
    }
}
