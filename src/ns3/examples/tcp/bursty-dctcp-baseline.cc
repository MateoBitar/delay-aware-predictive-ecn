#include <random>
#include <utility>
#include "ns3/applications-module.h"
#include "ns3/core-module.h"
#include "ns3/internet-module.h"
#include "ns3/network-module.h"
#include "ns3/point-to-point-module.h"
#include "ns3/traffic-control-module.h"
#include "ns3/tcp-l4-protocol.h"
#include "ns3/tcp-socket-base.h"
#include "ns3/sequence-number.h"
#include "ns3/tcp-socket-state.h"

#include <cstdint>
#include <algorithm>
#include <cmath>
#include <array>
#include <sstream>
#include <deque>
#include <stdexcept>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <map>
#include <string>
#include <vector>

using namespace ns3;

// Output files
std::ofstream queueOutput;
std::ofstream receiverOutput;
std::ofstream finalReceiverOutput;
std::ofstream shortFctOutput;
std::ofstream shortFlowRxOutput;

// Research v2: background application-delivery instrumentation.
std::ofstream backgroundRxOutput;
Ipv4Address backgroundSenderAddress1;
Ipv4Address backgroundSenderAddress2;
uint64_t backgroundDelivered1 = 0;
uint64_t backgroundDelivered2 = 0;

std::ofstream predictionOutput;

// Queue-trend prediction state. In baseline mode this remains logging only.
// The trend-experimental mode adjusts RED thresholds online; it is NOT
// equivalent to TT-PECN and needs queue-disc-level validation.
double predictionThresholdPackets = 20.0;
double predictionHorizonMs = 5.0;
double previousQueueTime = -1.0;
uint32_t previousQueueSize = 0;
std::string controllerMode = "baseline";
std::string workloadMode = "sustained";
std::string burstSchedule = "original";

std::string workloadVariation = "none";
uint64_t workloadSeed = 101;
double backgroundJitterMs = 10.0;
double shortFlowJitterMs = 5.0;
double shortFlowSizeVariation = 0.30;
uint32_t shortFlowBaseBytes = 100000;
    uint32_t linkDelayUs = 10;
double activeMinTh = 20.0, activeMaxTh = 60.0;
double configuredMinTh = 20.0, configuredMaxTh = 60.0;
double earlyMinTh = 10.0, earlyMaxTh = 30.0;
std::ofstream controllerOutput;
std::deque<double> recentQueue;
std::string mlModelPath = "";
double minActiveMs = 10.0;
double releaseBelowPackets = 8.0;
uint32_t negativeReleaseSamples = 5;
uint32_t consecutiveNegativeSamples = 0;
double nextReleaseAllowedSec = 0.0;
bool controllerEarlyActive = false;
std::array<double, 6> mlMean{}, mlStd{}, mlCoef{};
double mlBias = 0, mlCutoff = 0.5;
bool mlLoaded = false;
std::ofstream inferenceOutput;

void LoadMlModel(const std::string& path)
{
    std::ifstream file(path);
    if (!file) throw std::runtime_error("Cannot read ML model file: " + path);
    std::string signature;
    file >> signature;
    if (signature != "NS3_LOGISTIC_V1") throw std::runtime_error("Invalid ML model format");
    double horizon, threshold;
    file >> horizon >> threshold >> mlCutoff >> mlBias;
    if (std::abs(horizon-predictionHorizonMs)>1e-6 ||
        std::abs(threshold-predictionThresholdPackets)>1e-6)
       throw std::runtime_error("Model target horizon or queue threshold differs from simulation");
    for (auto& x : mlMean) file >> x;
    for (auto& x : mlStd) file >> x;
    for (auto& x : mlCoef) file >> x;
    if (!file || mlCutoff<=0 || mlCutoff>=1) throw std::runtime_error("Incomplete ML model");
    for (auto x : mlStd) if (x<=0) throw std::runtime_error("Invalid ML scale");
    mlLoaded = true;
}

double PredictMl()
{
    if (recentQueue.size()<6 || !mlLoaded) return 0.0;
    const auto q = [&] (size_t back) {return recentQueue[recentQueue.size()-1-back];};
    double sum=0, lo=q(0), hi=q(0);
    for (size_t i=0;i<6;++i) {sum+=q(i); lo=std::min(lo,q(i));hi=std::max(hi,q(i));}
    const std::array<double,6> features = {q(0),q(0)-q(1),(q(0)-q(3))/3.0,
        (q(0)-q(5))/5.0,sum/6.0,hi-lo};
    double logit=mlBias;
    for (size_t i=0;i<6;++i) logit+=mlCoef[i]*(features[i]-mlMean[i])/mlStd[i];
    return logit>=0 ? 1.0/(1.0+std::exp(-logit)) : std::exp(logit)/(1.0+std::exp(logit));
}

// Note that RED internally caches threshold-dependent coefficients at initialization.
// Changing thresholds during a run is exploratory until that behavior is validated.



// The background PacketSink receives TCP application payloads.
// RxWithAddresses exposes the remote endpoint, allowing sender
// identity to be determined without guessing from packet timing.
void
TraceBackgroundRx(
    Ptr<const Packet> packet,
    const Address& from,
    const Address& local)
{
    if (!InetSocketAddress::IsMatchingType(from))
    {
        throw std::runtime_error(
            "Unexpected non-IPv4 background sender");
    }

    InetSocketAddress endpoint =
        InetSocketAddress::ConvertFrom(from);

    uint32_t senderId = 0;
    uint64_t cumulativeBytes = 0;

    if (endpoint.GetIpv4() == backgroundSenderAddress1)
    {
        senderId = 1;
        backgroundDelivered1 += packet->GetSize();
        cumulativeBytes = backgroundDelivered1;
    }
    else if (endpoint.GetIpv4() == backgroundSenderAddress2)
    {
        senderId = 2;
        backgroundDelivered2 += packet->GetSize();
        cumulativeBytes = backgroundDelivered2;
    }
    else
    {
        throw std::runtime_error(
            "Unknown background sender address");
    }

    backgroundRxOutput
        << std::fixed << std::setprecision(9)
        << Simulator::Now().GetSeconds() << ","
        << senderId << ","
        << endpoint.GetPort() << ","
        << packet->GetSize() << ","
        << cumulativeBytes << "\n";
}

std::map<uint16_t, double> shortFlowStartTimes;
std::map<uint16_t, uint64_t> shortFlowRxBytes;
std::map<uint16_t, uint64_t> shortFlowTargetBytes;
std::map<uint16_t, bool> shortFlowCompleted;

void
TraceShortFlowRx(
    uint16_t flowId,
    Ptr<const Packet> packet,
    const Address& from)
{
    shortFlowRxBytes[flowId] += packet->GetSize();
    shortFlowRxOutput
        << std::fixed << std::setprecision(6)
        << Simulator::Now().GetSeconds() << " "
        << flowId << " "
        << packet->GetSize() << " "
        << shortFlowRxBytes[flowId]
        << std::endl;

    const uint64_t targetBytes = shortFlowTargetBytes.at(flowId);

    if (!shortFlowCompleted[flowId] &&
        shortFlowRxBytes[flowId] >= targetBytes)
    {
        shortFlowCompleted[flowId] = true;

        const double finishTime =
            Simulator::Now().GetSeconds();

        const double startTime =
            shortFlowStartTimes[flowId];

        const double fctMs =
            (finishTime - startTime) * 1000.0;

        shortFctOutput
            << std::fixed << std::setprecision(6)
            << flowId << " "
            << startTime << " "
            << finishTime << " "
            << fctMs << " "
            << shortFlowRxBytes[flowId]
            << std::endl;
    }
}
std::ofstream ecnOutput;
std::ofstream senderOutput;
std::ofstream cwndOutput;
std::ofstream ccResponseOutput;
std::ofstream retransmissionOutput;
std::ofstream shortFlowStateOutput;
std::ofstream shortFlowTxOutput;
std::ofstream dropOutput;
std::ofstream shortFlowSnapshotOutput;

// Latest event-observed TCP state for short flow 0. Values remain -1 until
// the corresponding trace reports a value; periodic rows therefore do not
// pretend that unobserved initial values are known.
int64_t shortFlow0Cwnd = -1;
int64_t shortFlow0BytesInFlight = -1;
int64_t shortFlow0Rwnd = -1;
int64_t shortFlow0HighestRxAck = -1;

void
TraceShortFlowSnapshot()
{
    if (shortFlowSnapshotOutput.is_open())
    {
        shortFlowSnapshotOutput
            << std::fixed << std::setprecision(9)
            << Simulator::Now().GetSeconds() << " "
            << shortFlow0Cwnd << " "
            << shortFlow0BytesInFlight << " "
            << shortFlow0Rwnd << " "
            << shortFlow0HighestRxAck << std::endl;
    }

    // Simulator::Stop() ends the run; this recurring diagnostic event does
    // not change packet handling or congestion-control behavior.
    Simulator::Schedule(MilliSeconds(1), &TraceShortFlowSnapshot);
}

// ------------------------------------------------------------
// Short-flow TCP retransmission trace
// ------------------------------------------------------------
void
TraceShortRetransmission(
    uint16_t flowId,
    Ptr<const Packet> packet,
    const TcpHeader& header,
    const Address& localAddr,
    const Address& peerAddr,
    Ptr<const TcpSocketBase> socket)
{
    retransmissionOutput
        << std::fixed << std::setprecision(6)
        << Simulator::Now().GetSeconds() << " "
        << flowId << " "
        << header.GetSequenceNumber().GetValue() << " "
        << header.GetSourcePort() << " "
        << header.GetDestinationPort() << " "
        << packet->GetSize() << std::endl;
}

// ------------------------------------------------------------
// Short-flow TCP transmission trace
// ------------------------------------------------------------
void
TraceShortFlowTx(
    uint16_t flowId,
    Ptr<const Packet> packet,
    const TcpHeader& header,
    Ptr<const TcpSocketBase> socket)
{
    shortFlowTxOutput
        << std::fixed << std::setprecision(9)
        << Simulator::Now().GetSeconds() << " "
        << flowId << " "
        << header.GetSequenceNumber().GetValue() << " "
        << header.GetSourcePort() << " "
        << header.GetDestinationPort() << " "
        << packet->GetSize() << std::endl;
}

// ------------------------------------------------------------
// Find the active TCP socket for a short flow and attach traces
// ------------------------------------------------------------
// ------------------------------------------------------------
// Short-flow TCP state changes: diagnostic trace
// ------------------------------------------------------------
void
TraceShortFlowTime(uint16_t flowId, Time oldValue, Time newValue)
{
    shortFlowStateOutput
        << std::fixed << std::setprecision(9)
        << Simulator::Now().GetSeconds() << " "
        << flowId << " "
        << "RTO" << " "
        << oldValue.GetSeconds() << " "
        << newValue.GetSeconds() << std::endl;
}

void
TraceShortFlowUint32(uint16_t flowId,
                     const char* stateName,
                     uint32_t oldValue,
                     uint32_t newValue)
{
    if (flowId == 0)
    {
        if (std::string(stateName) == "CongestionWindow")
        {
            shortFlow0Cwnd = newValue;
        }
        else if (std::string(stateName) == "BytesInFlight")
        {
            shortFlow0BytesInFlight = newValue;
        }
        else if (std::string(stateName) == "RWND")
        {
            shortFlow0Rwnd = newValue;
        }
    }

    shortFlowStateOutput
        << std::fixed << std::setprecision(9)
        << Simulator::Now().GetSeconds() << " "
        << flowId << " "
        << stateName << " "
        << oldValue << " "
        << newValue << std::endl;
}

void
TraceShortFlowSequenceNumber(
    uint16_t flowId,
    const char* stateName,
    SequenceNumber32 oldValue,
    SequenceNumber32 newValue)
{
    if (flowId == 0 && std::string(stateName) == "HighestRxAck")
    {
        shortFlow0HighestRxAck = newValue.GetValue();
    }

    shortFlowStateOutput
        << std::fixed << std::setprecision(9)
        << Simulator::Now().GetSeconds() << " "
        << flowId << " "
        << stateName << " "
        << oldValue.GetValue() << " "
        << newValue.GetValue() << std::endl;
}

void
TraceShortFlowCongState(
    uint16_t flowId,
    TcpSocketState::TcpCongState_t oldValue,
    TcpSocketState::TcpCongState_t newValue)
{
    shortFlowStateOutput
        << std::fixed << std::setprecision(9)
        << Simulator::Now().GetSeconds() << " "
        << flowId << " "
        << "CongState" << " "
        << static_cast<unsigned int>(oldValue) << " "
        << static_cast<unsigned int>(newValue) << std::endl;
}

void
ConnectShortFlowSocketTrace(
    Ptr<Node> node,
    uint16_t flowId,
    uint16_t expectedPeerPort)
{
    Ptr<TcpL4Protocol> tcp = node->GetObject<TcpL4Protocol>();
    if (tcp == nullptr)
    {
        throw std::runtime_error(
            "Could not find TcpL4Protocol for short-flow sender");
    }

    ObjectMapValue sockets;
    tcp->GetAttribute("SocketList", sockets);

    for (auto it = sockets.Begin(); it != sockets.End(); ++it)
    {
        Ptr<TcpSocketBase> socket =
            DynamicCast<TcpSocketBase>(it->second);

        if (socket == nullptr)
        {
            continue;
        }

        Address peerAddress;
        if (socket->GetPeerName(peerAddress) != 0)
        {
            continue;
        }

        if (!InetSocketAddress::IsMatchingType(peerAddress))
        {
            continue;
        }

        const uint16_t peerPort =
            InetSocketAddress::ConvertFrom(peerAddress).GetPort();

        if (peerPort != expectedPeerPort)
        {
            continue;
        }

        if (!socket->TraceConnectWithoutContext(
                "Tx",
                MakeBoundCallback(&TraceShortFlowTx, flowId)))
        {
            throw std::runtime_error(
                "Could not connect short-flow TCP Tx trace");
        }

        if (!socket->TraceConnectWithoutContext(
                "Retransmission",
                MakeBoundCallback(&TraceShortRetransmission, flowId)))
        {
            throw std::runtime_error(
                "Could not connect direct TCP retransmission trace");
        }

        if (!socket->TraceConnectWithoutContext(
                "RTO",
                MakeBoundCallback(&TraceShortFlowTime, flowId)))
        {
            throw std::runtime_error("Could not connect short-flow RTO trace");
        }

        if (!socket->TraceConnectWithoutContext(
                "CongestionWindow",
                MakeBoundCallback(
                    &TraceShortFlowUint32, flowId, "CongestionWindow")))
        {
            throw std::runtime_error(
                "Could not connect short-flow CongestionWindow trace");
        }

        if (!socket->TraceConnectWithoutContext(
                "BytesInFlight",
                MakeBoundCallback(
                    &TraceShortFlowUint32, flowId, "BytesInFlight")))
        {
            throw std::runtime_error(
                "Could not connect short-flow BytesInFlight trace");
        }

        if (!socket->TraceConnectWithoutContext(
                "RWND",
                MakeBoundCallback(
                    &TraceShortFlowUint32, flowId, "RWND")))
        {
            throw std::runtime_error(
                "Could not connect short-flow RWND trace");
        }

        if (!socket->TraceConnectWithoutContext(
                "HighestRxAck",
                MakeBoundCallback(
                    &TraceShortFlowSequenceNumber, flowId, "HighestRxAck")))
        {
            throw std::runtime_error(
                "Could not connect short-flow HighestRxAck trace");
        }

        if (!socket->TraceConnectWithoutContext(
                "CongState",
                MakeBoundCallback(&TraceShortFlowCongState, flowId)))
        {
            throw std::runtime_error(
                "Could not connect short-flow CongState trace");
        }

        std::cout << "Attached TCP traces: flow=" << flowId
                  << " peerPort=" << peerPort << std::endl;
        if (flowId == 0)
        {
            Simulator::Schedule(
                MilliSeconds(1),
                &TraceShortFlowSnapshot);
        }
        return;
    }

    std::cerr << "ERROR: no TCP socket found for flow " << flowId
              << " peerPort=" << expectedPeerPort << std::endl;

    throw std::runtime_error(
        "Could not find the active TCP socket for a short flow");
}

// ------------------------------------------------------------

// Bottleneck queue-disc drop trace
// ------------------------------------------------------------
void
TraceQueueDrop(Ptr<const QueueDiscItem> item, const char* reason)
{
    Ptr<Packet> packet = item->GetPacket()->Copy();
    TcpHeader header;
    uint32_t sequence = 0;
    uint16_t sourcePort = 0;
    uint16_t destinationPort = 0;

    if (packet->PeekHeader(header) > 0)
    {
        sequence = header.GetSequenceNumber().GetValue();
        sourcePort = header.GetSourcePort();
        destinationPort = header.GetDestinationPort();
    }

    dropOutput
        << std::fixed << std::setprecision(6)
        << Simulator::Now().GetSeconds() << " "
        << sourcePort << " " << destinationPort << " "
        << sequence << " " << packet->GetSize() << " "
        << reason << std::endl;
}

// ------------------------------------------------------------
// Queue monitoring
// ------------------------------------------------------------

void
CheckQueue(Ptr<QueueDisc> queue)
{
    const double now = Simulator::Now().GetSeconds();
    const uint32_t qSize = queue->GetNPackets();

    // Estimated queueing delay at the 100 Mbps bottleneck.
    Time queueDelay =
        Seconds(static_cast<double>(qSize * 1500 * 8) / 1e8);

    queueOutput << std::fixed << std::setprecision(6)
                << now << " "
                << qSize << " "
                << queueDelay.GetMicroSeconds()
                << std::endl;

    // Trend-based forecast using successive 1 ms queue samples.
    // This is a queue-size proxy, not RED's internal average.
    double trendPacketsPerMs = 0.0;
    double predictedCrossingMs = -1.0;
    int alert = 0;

    if (previousQueueTime >= 0.0 && now > previousQueueTime)
    {
        const double elapsedMs = (now - previousQueueTime) * 1000.0;
        trendPacketsPerMs =
            (static_cast<double>(qSize) - previousQueueSize) / elapsedMs;

        if (qSize < predictionThresholdPackets &&
            trendPacketsPerMs > 0.0)
        {
            predictedCrossingMs =
                (predictionThresholdPackets - qSize) / trendPacketsPerMs;

            if (predictedCrossingMs >= 0.0 &&
                predictedCrossingMs <= predictionHorizonMs)
            {
                alert = 1;
            }
        }
    }

    recentQueue.push_back(static_cast<double>(qSize));
    if (recentQueue.size()>6) recentQueue.pop_front();
    double mlProbability =
        (controllerMode == "ml-adapted" ||
         controllerMode == "ml-prediction-release") ? PredictMl() : -1.0;
    bool desiredAlert =
        (controllerMode == "ml-adapted" ||
         controllerMode == "ml-prediction-release") ?
        (recentQueue.size()==6 && qSize < predictionThresholdPackets && mlProbability >= mlCutoff) : alert;
    if (inferenceOutput.is_open())
       inferenceOutput << std::fixed << std::setprecision(6) << now << " " << qSize
                       << " " << mlProbability << " " << desiredAlert << std::endl;

    predictionOutput << std::fixed << std::setprecision(6)
                     << now << " "
                     << qSize << " "
                     << trendPacketsPerMs << " "
                     << predictedCrossingMs << " "
                     << alert << " "
                     << predictionThresholdPackets << " "
                     << predictionHorizonMs
                     << std::endl;

    const bool predictionReleaseMode =
        controllerMode == "trend-prediction-release" ||
        controllerMode == "ml-prediction-release";

    if (controllerMode == "trend-experimental" ||
        controllerMode == "trend-hysteresis" ||
        controllerMode == "ml-adapted" ||
        predictionReleaseMode)
    {
        if (predictionReleaseMode)
        {
            if (desiredAlert)
                consecutiveNegativeSamples = 0;
            else
                ++consecutiveNegativeSamples;

            if (!controllerEarlyActive && desiredAlert)
            {
                controllerEarlyActive = true;
                nextReleaseAllowedSec = now + minActiveMs / 1000.0;
                consecutiveNegativeSamples = 0;
            }
            else if (controllerEarlyActive &&
                     now >= nextReleaseAllowedSec &&
                     consecutiveNegativeSamples >= negativeReleaseSamples)
            {
                controllerEarlyActive = false;
            }
        }
        else
        {
            if (!controllerEarlyActive && desiredAlert)
            {
                controllerEarlyActive = true;
                nextReleaseAllowedSec = now + minActiveMs / 1000.0;
            }
            else if (controllerEarlyActive &&
                     now >= nextReleaseAllowedSec &&
                     !desiredAlert &&
                     qSize <= releaseBelowPackets)
            {
                controllerEarlyActive = false;
            }
        }
        const double desiredMin = controllerEarlyActive ? earlyMinTh : configuredMinTh;
        const double desiredMax = controllerEarlyActive ? earlyMaxTh : configuredMaxTh;
        if (desiredMin != activeMinTh || desiredMax != activeMaxTh)
        {
            Ptr<RedQueueDisc> red = DynamicCast<RedQueueDisc>(queue);
            if (!red) throw std::runtime_error("Expected RedQueueDisc at bottleneck");
            red->SetTh(desiredMin, desiredMax);
            activeMinTh = desiredMin;
            activeMaxTh = desiredMax;
            controllerOutput << std::fixed << std::setprecision(6)
                             << now << " " << controllerEarlyActive << " " << qSize << " "
                             << activeMinTh << " " << activeMaxTh << std::endl;
        }
    }

    previousQueueTime = now;
    previousQueueSize = qSize;

    Simulator::Schedule(
        MilliSeconds(1),
        &CheckQueue,
        queue);
}

// ------------------------------------------------------------
// ECN mark trace
// ------------------------------------------------------------

void
TraceEcnMark(Ptr<const QueueDiscItem> item, const char* reason)
{
    Ptr<Packet> packet = item->GetPacket()->Copy();

    uint32_t packetBytes = packet->GetSize();
    uint32_t tcpSeq = 0;
    uint16_t srcPort = 0;
    uint16_t dstPort = 0;

    TcpHeader tcpHeader;

    if (packet->PeekHeader(tcpHeader) > 0)
    {
        tcpSeq = tcpHeader.GetSequenceNumber().GetValue();
        srcPort = tcpHeader.GetSourcePort();
        dstPort = tcpHeader.GetDestinationPort();
    }

    ecnOutput
        << std::fixed << std::setprecision(6)
        << Simulator::Now().GetSeconds()
        << " "
        << packetBytes
        << " "
        << tcpSeq
        << " "
        << srcPort
        << " "
        << dstPort
        << " "
        << reason
        << std::endl;
}

void
TraceEcnStateS1(
    const TcpSocketState::EcnState_t oldState,
    const TcpSocketState::EcnState_t newState)
{
    senderOutput
        << std::fixed << std::setprecision(6)
        << Simulator::Now().GetSeconds()
        << " S1 ECN_STATE "
        << TcpSocketState::EcnStateName[oldState]
        << " -> "
        << TcpSocketState::EcnStateName[newState]
        << std::endl;
}

void
TraceEcnStateS2(
    const TcpSocketState::EcnState_t oldState,
    const TcpSocketState::EcnState_t newState)
{
    senderOutput
        << std::fixed << std::setprecision(6)
        << Simulator::Now().GetSeconds()
        << " S2 ECN_STATE "
        << TcpSocketState::EcnStateName[oldState]
        << " -> "
        << TcpSocketState::EcnStateName[newState]
        << std::endl;
}

// ------------------------------------------------------------
// Progress output
// ------------------------------------------------------------

void
PrintProgress()
{
    std::cout << "Simulation time: "
              << std::fixed << std::setprecision(3)
              << Simulator::Now().GetSeconds()
              << " s"
              << std::endl;

    Simulator::Schedule(
        MilliSeconds(100),
        &PrintProgress);
}

// ------------------------------------------------------------
// Receiver packet trace
// ------------------------------------------------------------

void
TraceCwndS1(uint32_t oldCwnd, uint32_t newCwnd)
{
    cwndOutput
        << std::fixed << std::setprecision(6)
        << Simulator::Now().GetSeconds()
        << " S1 "
        << oldCwnd
        << " " << newCwnd
        << std::endl;
}

void
TraceCwndS2(uint32_t oldCwnd, uint32_t newCwnd)
{
    cwndOutput
        << std::fixed << std::setprecision(6)
        << Simulator::Now().GetSeconds()
        << " S2 "
        << oldCwnd
        << " " << newCwnd
        << std::endl;
}

void
TraceSsThreshS1(uint32_t oldValue, uint32_t newValue)
{
    ccResponseOutput << std::fixed << std::setprecision(6)
                     << Simulator::Now().GetSeconds()
                     << " S1 SSTHRESH " << oldValue << " " << newValue
                     << std::endl;
}

void
TraceSsThreshS2(uint32_t oldValue, uint32_t newValue)
{
    ccResponseOutput << std::fixed << std::setprecision(6)
                     << Simulator::Now().GetSeconds()
                     << " S2 SSTHRESH " << oldValue << " " << newValue
                     << std::endl;
}

void
TraceCwndInflS1(uint32_t oldValue, uint32_t newValue)
{
    ccResponseOutput << std::fixed << std::setprecision(6)
                     << Simulator::Now().GetSeconds()
                     << " S1 CWND_INFL " << oldValue << " " << newValue
                     << std::endl;
}

void
TraceCwndInflS2(uint32_t oldValue, uint32_t newValue)
{
    ccResponseOutput << std::fixed << std::setprecision(6)
                     << Simulator::Now().GetSeconds()
                     << " S2 CWND_INFL " << oldValue << " " << newValue
                     << std::endl;
}

void
TracePacingS1(DataRate oldValue, DataRate newValue)
{
    ccResponseOutput << std::fixed << std::setprecision(6)
                     << Simulator::Now().GetSeconds()
                     << " S1 PACING "
                     << oldValue.GetBitRate() << " " << newValue.GetBitRate()
                     << std::endl;
}

void
TracePacingS2(DataRate oldValue, DataRate newValue)
{
    ccResponseOutput << std::fixed << std::setprecision(6)
                     << Simulator::Now().GetSeconds()
                     << " S2 PACING "
                     << oldValue.GetBitRate() << " " << newValue.GetBitRate()
                     << std::endl;
}

void
TraceEcnEchoS1(SequenceNumber32 oldValue, SequenceNumber32 newValue)
{
    ccResponseOutput << std::fixed << std::setprecision(6)
                     << Simulator::Now().GetSeconds()
                     << " S1 ECN_ECHO "
                     << oldValue.GetValue() << " " << newValue.GetValue()
                     << std::endl;
}

void
TraceEcnEchoS2(SequenceNumber32 oldValue, SequenceNumber32 newValue)
{
    ccResponseOutput << std::fixed << std::setprecision(6)
                     << Simulator::Now().GetSeconds()
                     << " S2 ECN_ECHO "
                     << oldValue.GetValue() << " " << newValue.GetValue()
                     << std::endl;
}

// ------------------------------------------------------------
// Session-specific background TCP tracing.
// Session IDs follow the order of installed background apps.
// ------------------------------------------------------------

void
TraceBackgroundCwnd(uint32_t senderId,
                    uint32_t sessionId,
                    uint32_t oldValue,
                    uint32_t newValue)
{
    ccResponseOutput
        << std::fixed << std::setprecision(9)
        << Simulator::Now().GetSeconds()
        << " S" << senderId << "_" << sessionId
        << " BG_CWND "
        << oldValue << " " << newValue
        << std::endl;
}

void
TraceBackgroundEcnEcho(uint32_t senderId,
                       uint32_t sessionId,
                       SequenceNumber32 oldValue,
                       SequenceNumber32 newValue)
{
    ccResponseOutput
        << std::fixed << std::setprecision(9)
        << Simulator::Now().GetSeconds()
        << " S" << senderId << "_" << sessionId
        << " BG_ECN_ECHO "
        << oldValue.GetValue()
        << " " << newValue.GetValue()
        << std::endl;
}

void
TraceBackgroundEcnState(uint32_t senderId,
                        uint32_t sessionId,
                        TcpSocketState::EcnState_t oldState,
                        TcpSocketState::EcnState_t newState)
{
    senderOutput
        << std::fixed << std::setprecision(9)
        << Simulator::Now().GetSeconds()
        << " S" << senderId << "_" << sessionId
        << " BG_ECN_STATE "
        << TcpSocketState::EcnStateName[oldState]
        << " -> "
        << TcpSocketState::EcnStateName[newState]
        << std::endl;
}

void
ConnectBackgroundSessionTrace(Ptr<Application> application,
                              uint32_t senderId,
                              uint32_t sessionId)
{
    Ptr<BulkSendApplication> bulk =
        DynamicCast<BulkSendApplication>(application);

    if (bulk == nullptr)
    {
        throw std::runtime_error(
            "Background application is not BulkSendApplication");
    }

    Ptr<TcpSocketBase> socket =
        DynamicCast<TcpSocketBase>(bulk->GetSocket());

    if (socket == nullptr)
    {
        throw std::runtime_error(
            "Background TCP socket is not available");
    }

    if (!socket->TraceConnectWithoutContext(
            "CongestionWindow",
            MakeBoundCallback(
                &TraceBackgroundCwnd, senderId, sessionId)))
    {
        throw std::runtime_error(
            "Background CongestionWindow trace failed");
    }

    if (!socket->TraceConnectWithoutContext(
            "EcnEchoSeq",
            MakeBoundCallback(
                &TraceBackgroundEcnEcho, senderId, sessionId)))
    {
        throw std::runtime_error(
            "Background EcnEchoSeq trace failed");
    }

    if (!socket->TraceConnectWithoutContext(
            "EcnState",
            MakeBoundCallback(
                &TraceBackgroundEcnState, senderId, sessionId)))
    {
        throw std::runtime_error(
            "Background EcnState trace failed");
    }

    std::cout
        << "Attached background TCP traces: sender="
        << senderId
        << " session=" << sessionId
        << std::endl;
}

void
TraceSenderTx(
    Ptr<const Packet> packet,
    const Address& from,
    const Address& to,
    const SeqTsSizeHeader& header)
{
    senderOutput
        << std::fixed << std::setprecision(6)
        << Simulator::Now().GetSeconds()
        << " "
        << packet->GetSize()
        << std::endl;
}

void
TraceReceiver(
    Ptr<const Packet> packet,
    const Address& from)
{
    receiverOutput
        << std::fixed << std::setprecision(6)
        << Simulator::Now().GetSeconds()
        << " "
        << packet->GetSize()
        << std::endl;
}

void
TraceFinalReceiver(
    Ptr<const Packet> packet,
    const Address& from)
{
    finalReceiverOutput
        << std::fixed << std::setprecision(6)
        << Simulator::Now().GetSeconds()
        << " "
        << packet->GetSize()
        << std::endl;
}

// ------------------------------------------------------------
// Main simulation
// ------------------------------------------------------------

int
main(int argc, char* argv[])
{
    // --------------------------------------------------------
    // Simulation parameters
    // --------------------------------------------------------

    Time startTime = Seconds(0.0);
    Time stopTime = Seconds(5.0);

    bool enableSwitchEcn = true;
    double minTh = 20.0;
    double maxTh = 60.0;
    double delAckTimeoutMs = 200.0;
    double earlyMin = 10.0;
    double earlyMax = 30.0;

    CommandLine cmd(__FILE__);

    cmd.AddValue(
        "enableSwitchEcn",
        "Enable ECN marking at the bottleneck",
        enableSwitchEcn);
    cmd.AddValue(
        "minTh",
        "RED minimum marking threshold in packets",
        minTh);
    cmd.AddValue(
        "maxTh",
        "RED maximum marking threshold in packets",
        maxTh);
    cmd.AddValue(
    	"delAckTimeoutMs",
    	"TCP delayed-ACK timeout in milliseconds (diagnostic)",
    	delAckTimeoutMs);
    cmd.AddValue(
        "predictorHorizonMs",
        "Queue-trend forecast horizon in milliseconds",
        predictionHorizonMs);

    cmd.AddValue("controllerMode", "baseline, trend-experimental, trend-hysteresis, ml-adapted, trend-prediction-release, ml-prediction-release", controllerMode);
    cmd.AddValue("mlModelPath", "Model file path generated by research_suite.py", mlModelPath);
    cmd.AddValue("minActiveMs", "Minimum early-mode activation duration (ms)", minActiveMs);
    cmd.AddValue("releaseBelowPackets", "Release early mode only below this queue occupancy", releaseBelowPackets);
    cmd.AddValue("negativeReleaseSamples", "Consecutive negative predictions needed to release early mode", negativeReleaseSamples);
    cmd.AddValue("earlyMinTh", "Experimental trend alert RED minimum", earlyMin);
    cmd.AddValue("earlyMaxTh", "Experimental trend alert RED maximum", earlyMax);
    cmd.AddValue(
        "workloadMode",
        "Background traffic: sustained or intermittent",
        workloadMode);

    cmd.AddValue(
        "burstSchedule",
        "Short-flow arrivals: original or aligned",
        burstSchedule);

    cmd.AddValue(
        "workloadVariation",
        "Workload randomization: none or controlled",
        workloadVariation);

    cmd.AddValue(
        "workloadSeed",
        "Independent deterministic workload scenario seed",
        workloadSeed);

    cmd.AddValue(
        "backgroundJitterMs",
        "Maximum absolute background start jitter in ms",
        backgroundJitterMs);

    cmd.AddValue(
        "shortFlowJitterMs",
        "Maximum absolute short-flow arrival jitter in ms",
        shortFlowJitterMs);

    cmd.AddValue(
        "shortFlowSizeVariation",
        "Maximum fractional short-flow size variation",
        shortFlowSizeVariation);

    cmd.AddValue(
        "shortFlowBaseBytes",
        "Nominal application bytes per short flow",
        shortFlowBaseBytes);

    cmd.AddValue(
        "linkDelayUs",
        "One-way propagation delay in microseconds per physical link",
        linkDelayUs);

    cmd.Parse(argc, argv);

    if (linkDelayUs < 1 || linkDelayUs > 10000)
    {
        throw std::runtime_error(
            "linkDelayUs must be between 1 and 10000 microseconds");
    }

    if (shortFlowBaseBytes < 10000 ||
        shortFlowBaseBytes > 250000)
    {
        throw std::runtime_error(
            "shortFlowBaseBytes must be within [10000,250000]");
    }
    if (controllerMode != "baseline" && controllerMode != "trend-experimental" &&
        controllerMode != "trend-hysteresis" && controllerMode != "ml-adapted" &&
        controllerMode != "trend-prediction-release" &&
        controllerMode != "ml-prediction-release")
    {
        std::cerr << "ERROR: unsupported controllerMode=" << controllerMode << std::endl;
        return 1;
    }
    if (earlyMin <= 0 || earlyMax <= earlyMin)
    {
        std::cerr << "ERROR: require 0 < earlyMinTh < earlyMaxTh" << std::endl;
        return 1;
    }
    if (workloadMode != "sustained" &&
        workloadMode != "intermittent")
    {
        std::cerr << "ERROR: unsupported workloadMode="
                  << workloadMode << std::endl;
        return 1;
    }

    if (burstSchedule != "original" &&
        burstSchedule != "aligned")
    {
        std::cerr << "ERROR: unsupported burstSchedule="
                  << burstSchedule << std::endl;
        return 1;
    }

    if (workloadVariation != "none" &&
        workloadVariation != "controlled")
    {
        throw std::runtime_error(
            "workloadVariation must be none or controlled");
    }

    if (workloadVariation == "controlled" &&
        (workloadMode != "intermittent" ||
         burstSchedule != "aligned"))
    {
        throw std::runtime_error(
            "Controlled variation requires intermittent aligned workload");
    }

    if (!std::isfinite(backgroundJitterMs) ||
        !std::isfinite(shortFlowJitterMs) ||
        !std::isfinite(shortFlowSizeVariation) ||
        backgroundJitterMs < 0.0 ||
        backgroundJitterMs > 20.0 ||
        shortFlowJitterMs < 0.0 ||
        shortFlowJitterMs > 10.0 ||
        shortFlowSizeVariation < 0.0 ||
        shortFlowSizeVariation > 0.50)
    {
        throw std::runtime_error(
            "Invalid workload variation parameters");
    }

    configuredMinTh = activeMinTh = minTh;
    configuredMaxTh = activeMaxTh = maxTh;
    earlyMinTh = earlyMin;
    earlyMaxTh = earlyMax;
    if (delAckTimeoutMs <= 0.0)
    {
        std::cerr << "ERROR: delAckTimeoutMs must be positive."
                  << std::endl;
        return 1;
    }
    if (minTh <= 0.0 || maxTh <= minTh)
    {
        std::cerr << "ERROR: Require minTh > 0 and maxTh > minTh."
                  << std::endl;
        return 1;
    }

    if (predictionHorizonMs <= 0.0)
    {
        std::cerr << "ERROR: predictorHorizonMs must be positive."
                  << std::endl;
        return 1;
    }

    predictionThresholdPackets = minTh;
    if (minActiveMs < 0 || releaseBelowPackets < 0 || negativeReleaseSamples == 0)
    {
        std::cerr << "ERROR: hold/release settings invalid" << std::endl;
        return 1;
    }
    if (controllerMode == "ml-adapted" || controllerMode == "ml-prediction-release")
    {
        if (mlModelPath.empty()) {std::cerr << "ERROR: --mlModelPath required" << std::endl; return 1;}
        LoadMlModel(mlModelPath);
    }

    // --------------------------------------------------------
    // Use DCTCP
    // --------------------------------------------------------

    Config::SetDefault(
        "ns3::TcpL4Protocol::SocketType",
        StringValue("ns3::TcpDctcp"));

    Config::SetDefault(
        "ns3::TcpSocket::SegmentSize",
        UintegerValue(1448));

    Config::SetDefault(
        "ns3::TcpSocket::DelAckCount",
        UintegerValue(2));

    Config::SetDefault(
    	"ns3::TcpSocket::DelAckTimeout",
    	TimeValue(MilliSeconds(delAckTimeoutMs)));

    GlobalValue::Bind(
        "ChecksumEnabled",
        BooleanValue(false));

    // --------------------------------------------------------
    // Topology
    //
    //       S1 ──┐
    //       S2 ──┼── SWITCH ── 100 Mbps ── R
    //       S3 ──┘
    //
    // --------------------------------------------------------

    NodeContainer senders;
    senders.Create(3);

    Ptr<Node> sw = CreateObject<Node>();
    Ptr<Node> receiver = CreateObject<Node>();

    // --------------------------------------------------------
    // Sender -> switch links
    // --------------------------------------------------------

    PointToPointHelper senderLink;

    senderLink.SetDeviceAttribute(
        "DataRate",
        StringValue("1Gbps"));

    senderLink.SetChannelAttribute(
        "Delay",
        TimeValue(MicroSeconds(linkDelayUs)));

    std::vector<NetDeviceContainer> senderDevices;

    for (uint32_t i = 0; i < 3; ++i)
    {
        senderDevices.push_back(
            senderLink.Install(
                senders.Get(i),
                sw));
    }

    // --------------------------------------------------------
    // Switch -> receiver bottleneck
    // --------------------------------------------------------

    PointToPointHelper bottleneckLink;

    bottleneckLink.SetDeviceAttribute(
        "DataRate",
        StringValue("100Mbps"));

    bottleneckLink.SetChannelAttribute(
        "Delay",
        TimeValue(MicroSeconds(linkDelayUs)));

    NetDeviceContainer bottleneckDevices =
        bottleneckLink.Install(
            sw,
            receiver);

    // --------------------------------------------------------
    // Install Internet stack
    // --------------------------------------------------------

    InternetStackHelper stack;

    stack.InstallAll();

    // --------------------------------------------------------
    // ECN-enabled RED queue at bottleneck
    // --------------------------------------------------------

    Config::SetDefault(
        "ns3::RedQueueDisc::UseEcn",
        BooleanValue(enableSwitchEcn));

    Config::SetDefault(
        "ns3::RedQueueDisc::UseHardDrop",
        BooleanValue(false));

    Config::SetDefault(
        "ns3::RedQueueDisc::MeanPktSize",
        UintegerValue(1500));

    Config::SetDefault(
        "ns3::RedQueueDisc::MaxSize",
        QueueSizeValue(
            QueueSize("1000p")));

    Config::SetDefault(
        "ns3::RedQueueDisc::QW",
        DoubleValue(1.0));

    TrafficControlHelper trafficControl;

    trafficControl.SetRootQueueDisc(
        "ns3::RedQueueDisc",
        "LinkBandwidth",
        StringValue("100Mbps"),
        "LinkDelay",
        StringValue("10us"),
        "MinTh",
        DoubleValue(minTh),
        "MaxTh",
        DoubleValue(maxTh));

    QueueDiscContainer bottleneckQueue =
        trafficControl.Install(
            bottleneckDevices.Get(0));

    // --------------------------------------------------------
    // IP addressing
    // --------------------------------------------------------

    Ipv4AddressHelper address;

    std::vector<Ipv4InterfaceContainer> senderInterfaces;

    address.SetBase(
        "10.1.1.0",
        "255.255.255.0");

    for (uint32_t i = 0; i < 3; ++i)
    {
        senderInterfaces.push_back(
            address.Assign(
                senderDevices[i]));

        address.NewNetwork();
    }

    address.SetBase(
        "10.10.1.0",
        "255.255.255.0");

    Ipv4InterfaceContainer bottleneckInterfaces =
        address.Assign(
            bottleneckDevices);

    Ipv4GlobalRoutingHelper::PopulateRoutingTables();

    backgroundSenderAddress1 =
        senderInterfaces.at(0).GetAddress(0);

    backgroundSenderAddress2 =
        senderInterfaces.at(1).GetAddress(0);


    // --------------------------------------------------------
    // Receiver
    // --------------------------------------------------------

    uint16_t port = 50000;

    Address sinkAddress(
        InetSocketAddress(
            Ipv4Address::GetAny(),
            port));

    PacketSinkHelper sinkHelper(
        "ns3::TcpSocketFactory",
        sinkAddress);

    ApplicationContainer sinkApp =
        sinkHelper.Install(receiver);

    Ptr<PacketSink> receiverSink =
        sinkApp.Get(0)->GetObject<PacketSink>();

    sinkApp.Start(startTime);
    sinkApp.Stop(stopTime);

    // Intermittent background-traffic scenario.
    // Separate BulkSend applications create fresh TCP connections
    // for each active interval.
    std::vector<std::pair<double, double>> backgroundWindows = {
        {0.10, 0.45},
        {0.85, 0.95},
        {1.30, 1.40},
        {1.65, 1.75},
        {2.05, 2.15},
        {2.35, 2.45},
        {2.75, 2.85},
        {3.25, 3.35},
        {3.85, 3.95}
    };

    // Independently seeded workload RNG streams.
    // These draws do not depend on controller mode or RngRun.
    std::mt19937_64 backgroundRng(
        workloadSeed ^ 0x9E3779B97F4A7C15ULL);

    std::mt19937_64 shortTimeRng(
        workloadSeed ^ 0xD1B54A32D192ED03ULL);

    std::mt19937_64 shortSizeRng(
        workloadSeed ^ 0x94D049BB133111EBULL);

    if (workloadVariation == "controlled")
    {
        std::uniform_real_distribution<double> jitter(
            -backgroundJitterMs / 1000.0,
             backgroundJitterMs / 1000.0);

        for (auto& window : backgroundWindows)
        {
            const double shift = jitter(backgroundRng);

            window.first += shift;
            window.second += shift;
        }
    }

    std::ofstream workloadManifest(
        "bursty-workload-manifest.csv",
        std::ios::out);

    if (!workloadManifest)
    {
        throw std::runtime_error(
            "Cannot open workload manifest");
    }

    workloadManifest
        << "record_type,id,sender,start_s,stop_s,max_bytes\n";

    for (size_t i = 0; i < backgroundWindows.size(); ++i)
    {
        const auto& window = backgroundWindows[i];

        for (uint32_t sender = 1; sender <= 2; ++sender)
        {
            workloadManifest
                << "background," << i
                << "," << sender
                << "," << std::fixed << std::setprecision(9)
                << window.first
                << "," << window.second
                << ",0\n";
        }
    }

    // --------------------------------------------------------
    // S1: long-lived TCP flow
    // --------------------------------------------------------

    BulkSendHelper longFlow1(
        "ns3::TcpSocketFactory",
        InetSocketAddress(
            bottleneckInterfaces.GetAddress(1),
            port));

    longFlow1.SetAttribute(
        "MaxBytes",
        UintegerValue(0));

    longFlow1.SetAttribute(
        "EnableSeqTsSizeHeader",
        BooleanValue(true));

    if (workloadMode == "sustained")
    {
        ApplicationContainer app1 =
            longFlow1.Install(senders.Get(0));

        app1.Start(Seconds(0.1));

        Simulator::Schedule(
            Seconds(0.1) + NanoSeconds(1),
            &ConnectBackgroundSessionTrace,
            app1.Get(0), 1u, 0u);
        app1.Stop(Seconds(5.0));

        app1.Get(0)->TraceConnectWithoutContext(
            "TxWithSeqTsSize",
            MakeCallback(&TraceSenderTx));
    }
    else
    {
        for (const auto& window : backgroundWindows)
        {
            ApplicationContainer app1 =
                longFlow1.Install(senders.Get(0));

            app1.Start(Seconds(window.first));

            Simulator::Schedule(
                Seconds(window.first) + NanoSeconds(1),
                &ConnectBackgroundSessionTrace,
                app1.Get(0), 1u,
                static_cast<uint32_t>(
                    &window - &backgroundWindows[0]));
            app1.Stop(Seconds(window.second));

            app1.Get(0)->TraceConnectWithoutContext(
                "TxWithSeqTsSize",
                MakeCallback(&TraceSenderTx));
        }
    }

    // --------------------------------------------------------
    // S2: long-lived TCP flow
    // --------------------------------------------------------

    BulkSendHelper longFlow2(
        "ns3::TcpSocketFactory",
        InetSocketAddress(
            bottleneckInterfaces.GetAddress(1),
            port));

    longFlow2.SetAttribute(
        "MaxBytes",
        UintegerValue(0));

    longFlow2.SetAttribute(
        "EnableSeqTsSizeHeader",
        BooleanValue(true));

    if (workloadMode == "sustained")
    {
        ApplicationContainer app2 =
            longFlow2.Install(senders.Get(1));

        app2.Start(Seconds(0.1));

        Simulator::Schedule(
            Seconds(0.1) + NanoSeconds(1),
            &ConnectBackgroundSessionTrace,
            app2.Get(0), 2u, 0u);
        app2.Stop(Seconds(5.0));

        app2.Get(0)->TraceConnectWithoutContext(
            "TxWithSeqTsSize",
            MakeCallback(&TraceSenderTx));
    }
    else
    {
        for (const auto& window : backgroundWindows)
        {
            ApplicationContainer app2 =
                longFlow2.Install(senders.Get(1));

            app2.Start(Seconds(window.first));

            Simulator::Schedule(
                Seconds(window.first) + NanoSeconds(1),
                &ConnectBackgroundSessionTrace,
                app2.Get(0), 2u,
                static_cast<uint32_t>(
                    &window - &backgroundWindows[0]));
            app2.Stop(Seconds(window.second));

            app2.Get(0)->TraceConnectWithoutContext(
                "TxWithSeqTsSize",
                MakeCallback(&TraceSenderTx));
        }
    }

    // --------------------------------------------------------
    // S3: bursty short TCP flows
    //
    // Each application represents one short flow.
    // Several flows are started close together to create bursts.
    // --------------------------------------------------------

    const uint32_t shortFlowBytes = shortFlowBaseBytes;

    std::vector<double> burstTimes =
    {
        1.00,
        1.02,
        1.04,
        1.20,
        1.22,
        1.24,
        1.50,
        1.52,
        1.54,
        1.80,
        1.82,
        1.84,
        2.20,
        2.22,
        2.24,
        2.50,
        2.52,
        2.54,
        3.00,
        3.02,
        3.04,
        3.50,
        3.52,
        3.54
    };

    // Congestion-aligned short-flow scenario.
    // Preserves the original 24-flow schedule as the default.
    if (burstSchedule == "aligned")
    {
        burstTimes = {
            0.860, 0.880, 0.900,
            1.310, 1.330, 1.350,
            1.660, 1.680, 1.700,
            2.060, 2.080, 2.100,
            2.360, 2.380, 2.400,
            2.760, 2.780, 2.800,
            3.260, 3.280, 3.300,
            3.860, 3.880, 3.900
        };
    }

    if (workloadVariation == "controlled")
    {
        std::uniform_real_distribution<double> jitter(
            -shortFlowJitterMs / 1000.0,
             shortFlowJitterMs / 1000.0);

        for (double& arrival : burstTimes)
        {
            arrival += jitter(shortTimeRng);
        }
    }

    std::vector<uint32_t> shortSizes(
        burstTimes.size(), shortFlowBytes);

    if (workloadVariation == "controlled")
    {
        std::uniform_real_distribution<double> factor(
            1.0 - shortFlowSizeVariation,
            1.0 + shortFlowSizeVariation);

        for (uint32_t& bytes : shortSizes)
        {
            bytes = static_cast<uint32_t>(
                std::llround(
                    static_cast<double>(shortFlowBytes) *
                    factor(shortSizeRng)));
        }
    }

    uint16_t shortFlowBasePort = 51000;
    uint16_t shortFlowId = 0;

    for (double time : burstTimes)
    {
        const uint16_t shortPort =
            shortFlowBasePort + shortFlowId;

        const uint16_t flowId =
            shortFlowId;

        Address shortSinkAddress(
            InetSocketAddress(
                Ipv4Address::GetAny(),
                shortPort));

        PacketSinkHelper shortSinkHelper(
            "ns3::TcpSocketFactory",
            shortSinkAddress);

        ApplicationContainer shortSinkApp =
            shortSinkHelper.Install(receiver);

        shortSinkApp.Start(startTime);
        shortSinkApp.Stop(stopTime);

        Ptr<PacketSink> shortSink =
            shortSinkApp.Get(0)->GetObject<PacketSink>();

        shortSink->TraceConnectWithoutContext(
            "Rx",
            MakeBoundCallback(
                &TraceShortFlowRx,
                flowId));

        shortFlowStartTimes[flowId] = time;
        shortFlowRxBytes[flowId] = 0;
        shortFlowTargetBytes[flowId] = shortSizes[flowId];
        shortFlowCompleted[flowId] = false;

        BulkSendHelper shortFlow(
            "ns3::TcpSocketFactory",
            InetSocketAddress(
                bottleneckInterfaces.GetAddress(1),
                shortPort));

        shortFlow.SetAttribute(
            "MaxBytes",
            UintegerValue(shortSizes[flowId]));

        ApplicationContainer app =
            shortFlow.Install(
                senders.Get(2));

        app.Start(
            Seconds(time));

        Simulator::Schedule(
            Seconds(time) + NanoSeconds(1),
            &ConnectShortFlowSocketTrace,
            senders.Get(2),
            flowId,
            shortPort);

        app.Stop(
            Seconds(time + 1.0));

        workloadManifest
            << "short_flow," << flowId
            << ",3,"
            << std::fixed << std::setprecision(9)
            << time
            << "," << (time + 1.0)
            << "," << shortSizes[flowId]
            << "\n";

        ++shortFlowId;
    }

    workloadManifest.close();

    // --------------------------------------------------------
    // Output files
    // --------------------------------------------------------

    queueOutput.open(
        "bursty-queue.dat",
        std::ios::out);

    inferenceOutput.open("bursty-ml-inference.dat", std::ios::out);
    if (!inferenceOutput.is_open()) throw std::runtime_error("Cannot open inference output");
    inferenceOutput << "# Time(s) QueuePackets Probability Alert" << std::endl;
    controllerOutput.open("bursty-controller-actions.dat", std::ios::out);
    if (!controllerOutput.is_open())
    {
        std::cerr << "ERROR: cannot open controller output" << std::endl;
        return 1;
    }
    controllerOutput << "# Time(s) Alert QueuePackets ActiveMinTh ActiveMaxTh" << std::endl;
    predictionOutput.open(
        "bursty-predictions.dat",
        std::ios::out);
    if (!predictionOutput.is_open())
    {
        std::cerr << "ERROR: Could not open bursty-predictions.dat"
                  << std::endl;
        return 1;
    }
    predictionOutput
        << "# Time(s) QueuePackets TrendPacketsPerMs PredictedCrossingMs Alert ThresholdPackets HorizonMs"
        << std::endl;

    receiverOutput.open(
        "bursty-receiver.dat",
        std::ios::out);

    ecnOutput.open(
        "bursty-ecn.dat",
        std::ios::out);

    senderOutput.open(
        "bursty-sender.dat",
        std::ios::out);

    cwndOutput.open(
        "bursty-cwnd.dat",
        std::ios::out);
    
    ccResponseOutput.open(
        "bursty-cc-response.dat",
        std::ios::out);

    retransmissionOutput.open(
        "bursty-retransmissions.dat", std::ios::out);

    shortFlowStateOutput.open(
        "bursty-short-flow-state.dat", std::ios::out);
    shortFlowStateOutput
        << "# Time(s) FlowId State OldValue NewValue" << std::endl;
    shortFlowTxOutput.open(
        "bursty-short-flow-tx.dat", std::ios::out);
    dropOutput.open(
        "bursty-drops.dat", std::ios::out);
    shortFlowSnapshotOutput.open(
        "bursty-short-flow-snapshot.dat", std::ios::out);
    if (!shortFlowSnapshotOutput.is_open())
    {
        std::cerr << "ERROR: Could not open bursty-short-flow-snapshot.dat"
                  << std::endl;
        return 1;
    }
    shortFlowSnapshotOutput
        << "# Time(s) CwndBytes BytesInFlightBytes RWNDBytes HighestRxAck"
        << std::endl;
    finalReceiverOutput.open(
        "bursty-final-receiver.dat",
        std::ios::out);

    shortFctOutput.open(
        "bursty-short-fct.dat",
        std::ios::out);
    backgroundRxOutput.open(
        "bursty-background-rx.csv",
        std::ios::out);

    if (!backgroundRxOutput)
    {
        throw std::runtime_error(
            "Cannot open background receiver trace");
    }

    backgroundRxOutput
        << "time_s,sender_id,source_port,"
        << "payload_bytes,cumulative_sender_bytes\n";

    shortFlowRxOutput.open(
        "bursty-short-flow-rx.dat",
        std::ios::out);
    shortFlowRxOutput
        << "# Time(s) FlowId PacketBytes CumulativeRxBytes"
        << std::endl;

    shortFctOutput
        << "# FlowId StartTime FinishTime FCT_ms RxBytes"
        << std::endl;

    queueOutput
        << "# Time(s) QueuePackets QueueDelay(us)"
        << std::endl;

    receiverOutput
        << "# Time(s) PacketBytes"
        << std::endl;

    ecnOutput
        << "# Time(s) PacketBytes TcpSequence SourcePort DestinationPort Reason"
        << std::endl;

    cwndOutput
        << "# Time(s) Sender OldCwnd NewCwnd"
        << std::endl;
    
    ccResponseOutput
        << "# Time(s) Sender Metric OldValue NewValue"
        << std::endl;

    retransmissionOutput
        << "# Time(s) FlowId TcpSequence SourcePort DestinationPort PacketBytes"
        << std::endl;
    shortFlowTxOutput
        << "# Time(s) FlowId TcpSequence SourcePort DestinationPort PacketBytes"
        << std::endl;
    dropOutput
        << "# Time(s) SourcePort DestinationPort TcpSequence PacketBytes Reason"
        << std::endl;

    // --------------------------------------------------------
    // Trace receiver packet arrivals
    // --------------------------------------------------------

    receiverSink->TraceConnectWithoutContext(
        "Rx",
        MakeCallback(&TraceReceiver));

    if (!receiverSink->TraceConnectWithoutContext(
            "RxWithAddresses",
            MakeCallback(&TraceBackgroundRx)))
    {
        throw std::runtime_error(
            "Cannot connect background RxWithAddresses trace");
    }

    receiverSink->TraceConnectWithoutContext(
        "Rx",
        MakeCallback(&TraceFinalReceiver));

    bottleneckQueue.Get(0)->TraceConnectWithoutContext(
        "Mark",
        MakeCallback(&TraceEcnMark));

    if (!bottleneckQueue.Get(0)->TraceConnectWithoutContext(
            "DropBeforeEnqueue", MakeCallback(&TraceQueueDrop)))
    {
        throw std::runtime_error("DropBeforeEnqueue trace connection failed");
    }
    if (!bottleneckQueue.Get(0)->TraceConnectWithoutContext(
            "DropAfterDequeue", MakeCallback(&TraceQueueDrop)))
    {
        throw std::runtime_error("DropAfterDequeue trace connection failed");
    }

    // --------------------------------------------------------
    // Start queue monitoring
    // --------------------------------------------------------
    if (workloadMode == "sustained")
    {
    Simulator::Schedule(
    MilliSeconds(101),
    []()
    {
        Config::ConnectWithoutContext(
            "/NodeList/0/$ns3::TcpL4Protocol/SocketList/0/EcnState",
            MakeCallback(&TraceEcnStateS1));

        Config::ConnectWithoutContext(
            "/NodeList/1/$ns3::TcpL4Protocol/SocketList/0/EcnState",
            MakeCallback(&TraceEcnStateS2));

        Config::ConnectWithoutContext(
            "/NodeList/0/$ns3::TcpL4Protocol/SocketList/0/CongestionWindow",
            MakeCallback(&TraceCwndS1));

        Config::ConnectWithoutContext(
            "/NodeList/1/$ns3::TcpL4Protocol/SocketList/0/CongestionWindow",
            MakeCallback(&TraceCwndS2));


        Config::ConnectWithoutContext(
            "/NodeList/0/$ns3::TcpL4Protocol/SocketList/0/SlowStartThreshold",
            MakeCallback(&TraceSsThreshS1));

        Config::ConnectWithoutContext(
            "/NodeList/1/$ns3::TcpL4Protocol/SocketList/0/SlowStartThreshold",
            MakeCallback(&TraceSsThreshS2));

        Config::ConnectWithoutContext(
            "/NodeList/0/$ns3::TcpL4Protocol/SocketList/0/CongestionWindowInflated",
            MakeCallback(&TraceCwndInflS1));

        Config::ConnectWithoutContext(
            "/NodeList/1/$ns3::TcpL4Protocol/SocketList/0/CongestionWindowInflated",
            MakeCallback(&TraceCwndInflS2));

        Config::ConnectWithoutContext(
            "/NodeList/0/$ns3::TcpL4Protocol/SocketList/0/PacingRate",
            MakeCallback(&TracePacingS1));

        Config::ConnectWithoutContext(
            "/NodeList/1/$ns3::TcpL4Protocol/SocketList/0/PacingRate",
            MakeCallback(&TracePacingS2));


        Config::ConnectWithoutContext(
            "/NodeList/0/$ns3::TcpL4Protocol/SocketList/0/EcnEchoSeq",
            MakeCallback(&TraceEcnEchoS1));

        Config::ConnectWithoutContext(
            "/NodeList/1/$ns3::TcpL4Protocol/SocketList/0/EcnEchoSeq",
            MakeCallback(&TraceEcnEchoS2));
    });
    }


    Simulator::Schedule(
        MilliSeconds(1),
        &CheckQueue,
        bottleneckQueue.Get(0));

    // --------------------------------------------------------
    // Progress output
    // --------------------------------------------------------

    Simulator::Schedule(
        MilliSeconds(100),
        &PrintProgress);

    // --------------------------------------------------------
    // Run
    // --------------------------------------------------------

    Simulator::Stop(
        stopTime + MilliSeconds(1));

    Simulator::Run();

    // --------------------------------------------------------
    // Cleanup
    // --------------------------------------------------------

    controllerOutput.close();
    inferenceOutput.close();
    queueOutput.close();
    predictionOutput.close();
    receiverOutput.close();
    finalReceiverOutput.close();
    shortFctOutput.close();
    shortFlowRxOutput.close();
    backgroundRxOutput.close();
    ecnOutput.close();
    senderOutput.close();
cwndOutput.close();
ccResponseOutput.close();
    retransmissionOutput.close();
    shortFlowTxOutput.close();
    dropOutput.close();
    shortFlowSnapshotOutput.close();

    Simulator::Destroy();

    return 0;
}
