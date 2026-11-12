from pathlib import Path

source = (
    Path.home()
    / "ns3-external-validation/ns-3.47/examples/tcp/bursty-dctcp-baseline.cc"
)

if not source.is_file():
    raise SystemExit(f"Missing source: {source}")

original = source.read_text()

if "externalManifestPath" in original:
    raise SystemExit("External replay mode already exists; nothing changed.")

text = original

def change(old, new):
    global text
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"Expected one matching source block, found {count}: {old[:80]!r}"
        )
    text = text.replace(old, new, 1)

change("#include <vector>\n",
       "#include <vector>\n#include <limits>\n")

change('std::string burstSchedule = "original";', '''
std::string burstSchedule = "original";
std::string externalManifestPath = "";

struct ExternalFlow {
    uint16_t id;
    double startSeconds;
    uint32_t sizeBytes;
    std::string trafficClass;
};

std::vector<ExternalFlow>
LoadExternalManifest(const std::string& path)
{
    std::ifstream input(path);
    if (!input)
        throw std::runtime_error("Cannot open external manifest: " + path);

    std::string line;
    if (!std::getline(input, line) ||
        line != "flow_id,start_s,size_bytes,traffic_class")
        throw std::runtime_error("Unexpected external manifest header");

    std::vector<ExternalFlow> flows;

    while (std::getline(input, line)) {
        if (line.empty()) continue;

        std::istringstream s(line);
        std::string id, start, size, cls, extra;

        if (!std::getline(s, id, ',') ||
            !std::getline(s, start, ',') ||
            !std::getline(s, size, ',') ||
            !std::getline(s, cls, ',') ||
            std::getline(s, extra, ','))
            throw std::runtime_error("Invalid manifest row: " + line);

        unsigned long ident = std::stoul(id);
        unsigned long long bytes = std::stoull(size);
        double t = std::stod(start);

        if (ident != flows.size() || ident > 999 ||
            bytes == 0 ||
            bytes > std::numeric_limits<uint32_t>::max() ||
            !std::isfinite(t) || t < 0 ||
            (cls != "short" && cls != "large") ||
            ((cls == "short") != (bytes <= 250000)))
            throw std::runtime_error("Invalid external flow: " + line);

        flows.push_back({
            static_cast<uint16_t>(ident),
            t,
            static_cast<uint32_t>(bytes),
            cls
        });
    }

    if (flows.empty())
        throw std::runtime_error("External manifest contains no flows");

    return flows;
}
'''.strip())

change('    cmd.Parse(argc, argv);', '''
    cmd.AddValue(
        "externalManifestPath",
        "External CSV workload manifest",
        externalManifestPath);

    cmd.Parse(argc, argv);

    const bool externalReplay = !externalManifestPath.empty();
    std::vector<ExternalFlow> externalFlows;

    if (externalReplay) {
        externalFlows = LoadExternalManifest(externalManifestPath);

        double lastStart = 0.0;
        uint64_t totalBytes = 0;

        for (const auto& flow : externalFlows) {
            lastStart = std::max(lastStart, flow.startSeconds);
            totalBytes += flow.sizeBytes;
        }

        // Conservative pilot deadline; actual completion is checked.
        double deadline = lastStart + 10.0 +
            2.0 * static_cast<double>(totalBytes) * 8.0 / 100000000.0;

        stopTime = Seconds(deadline);
    }
'''.rstrip())

change(
    '    for (size_t i = 0; i < backgroundWindows.size(); ++i)\n'
    '    {\n        const auto& window = backgroundWindows[i];',
    '    for (size_t i = 0; '
    'i < (externalReplay ? 0 : backgroundWindows.size()); ++i)\n'
    '    {\n        const auto& window = backgroundWindows[i];'
)

old = '    if (workloadMode == "sustained")\n    {'
if text.count(old) != 3:
    raise RuntimeError("Unexpected background-control source structure")
text = text.replace(
    old,
    '    if (!externalReplay && workloadMode == "sustained")\n    {'
)

old = ('    else\n    {\n'
       '        for (const auto& window : backgroundWindows)\n'
       '        {')
if text.count(old) != 2:
    raise RuntimeError("Unexpected background-session source structure")
text = text.replace(
    old,
    ('    else if (!externalReplay)\n    {\n'
     '        for (const auto& window : backgroundWindows)\n'
     '        {')
)

change(
    '    if (burstSchedule == "aligned")\n    {',
    '    if (!externalReplay && burstSchedule == "aligned")\n    {'
)

change(
    '    if (workloadVariation == "controlled")\n'
    '    {\n        std::uniform_real_distribution<double> jitter(\n'
    '            -shortFlowJitterMs / 1000.0,',
    '    if (!externalReplay && workloadVariation == "controlled")\n'
    '    {\n        std::uniform_real_distribution<double> jitter(\n'
    '            -shortFlowJitterMs / 1000.0,'
)

change(
    '    if (workloadVariation == "controlled")\n'
    '    {\n        std::uniform_real_distribution<double> factor(',
    '    if (!externalReplay && workloadVariation == "controlled")\n'
    '    {\n        std::uniform_real_distribution<double> factor('
)

change('    uint16_t shortFlowBasePort = 51000;', '''
    if (externalReplay) {
        burstTimes.clear();
        shortSizes.clear();

        for (const auto& flow : externalFlows) {
            burstTimes.push_back(flow.startSeconds);
            shortSizes.push_back(flow.sizeBytes);
        }
    }

    uint16_t shortFlowBasePort = 51000;
'''.rstrip())

change(
    '            shortFlow.Install(\n                senders.Get(2));',
    '            shortFlow.Install(\n'
    '                senders.Get(externalReplay ? (flowId % 3) : 2));'
)

change(
    '            &ConnectShortFlowSocketTrace,\n'
    '            senders.Get(2),',
    '            &ConnectShortFlowSocketTrace,\n'
    '            senders.Get(externalReplay ? (flowId % 3) : 2),'
)

change(
    '        app.Stop(\n            Seconds(time + 1.0));',
    '        app.Stop(\n'
    '            externalReplay ? stopTime - MilliSeconds(10)\n'
    '                           : Seconds(time + 1.0));'
)

change(
    '            << "," << (time + 1.0)\n'
    '            << "," << shortSizes[flowId]',
    '            << "," << (externalReplay ? '
    'stopTime.GetSeconds() - 0.01 : time + 1.0)\n'
    '            << "," << shortSizes[flowId]'
)

change('    Simulator::Run();', '''
    Simulator::Run();

    if (externalReplay) {
        for (const auto& flow : externalFlows) {
            if (!shortFlowCompleted.at(flow.id) ||
                shortFlowRxBytes.at(flow.id) != flow.sizeBytes) {
                throw std::runtime_error(
                    "External flow failed completion/byte accounting: " +
                    std::to_string(flow.id));
            }
        }

        std::cout << "PASS: external replay completed "
                  << externalFlows.size() << " flows" << std::endl;
    }
'''.rstrip())

backup = source.with_suffix(".cc.before_external_replay")
if backup.exists():
    raise SystemExit(f"Backup already exists: {backup}")

backup.write_text(original)
source.write_text(text)

print("PASS: Original C++ source backed up")
print("PASS: External CSV replay mode installed")
print("PASS: Legacy controller modes preserved")
print("SOURCE:", source)
