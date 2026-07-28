// Test-only differential probe for the explicitly UNFROZEN NORMAL/PASS v0 slice.

#include <cctype>
#include <cstdint>
#include <cstdio>
#include <iostream>
#include <string>
#include <vector>

#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#endif

#include "../game/collapsegoreducer.h"
#include "../game/gameaction.h"
#include "../game/rulesetidentity.h"

using nlohmann::json;
using namespace std;

namespace {

const string PROTOCOL_VERSION = "normal-pass-diff-v0-unfrozen";
constexpr size_t MAX_REQUEST_FRAME_BYTES = 1024 * 1024;
constexpr size_t MAX_RESPONSE_FRAME_BYTES = 16 * 1024 * 1024;
constexpr size_t MAX_EPISODE_STEPS = 160;

[[noreturn]] void failFrame(const string& message) {
  throw StringError("Malformed normal-pass differential frame: " + message);
}

bool readBoundedLine(istream& input, string& line, size_t lineNumber) {
  line.clear();
  while(true) {
    int next = input.get();
    if(next == istream::traits_type::eof()) {
      if(!input.eof())
        throw IOError("Could not read differential probe input");
      if(line.empty())
        return false;
      failFrame("line " + Global::sizeToString(lineNumber) + " is not newline-terminated");
    }
    if(next == '\n')
      return true;
    if(line.size() >= MAX_REQUEST_FRAME_BYTES)
      failFrame("line " + Global::sizeToString(lineNumber) + " exceeds the 1 MiB request limit");
    line.push_back(static_cast<char>(next));
  }
}

void requireExactFields(const json& value, const vector<string>& fields, const string& context) {
  if(!value.is_object() || value.size() != fields.size())
    failFrame(context + " must contain exactly the required fields");
  for(const string& field: fields) {
    if(value.find(field) == value.end())
      failFrame(context + " is missing field " + field);
  }
}

string requireString(const json& value, const string& context) {
  if(!value.is_string())
    failFrame(context + " must be a string");
  return value.get<string>();
}

int requireInt(const json& value, const string& context) {
  if(value.is_number_unsigned()) {
    uint64_t parsed = value.get<uint64_t>();
    if(parsed > static_cast<uint64_t>(INT32_MAX))
      failFrame(context + " is outside the supported integer range");
    return static_cast<int>(parsed);
  }
  if(value.is_number_integer()) {
    int64_t parsed = value.get<int64_t>();
    if(parsed < INT32_MIN || parsed > INT32_MAX)
      failFrame(context + " is outside the supported integer range");
    return static_cast<int>(parsed);
  }
  failFrame(context + " must be an integer");
}

void validateEpisodeId(const string& episodeId) {
  if(episodeId.empty() || episodeId.size() > 128)
    failFrame("episodeId must contain 1..128 identifier characters");
  for(unsigned char c: episodeId) {
    if(!std::isalnum(c) && c != '.' && c != '_' && c != '-')
      failFrame("episodeId may contain only ASCII letters, digits, '.', '_', and '-'");
  }
}

Player parseCandidateActor(const json& value) {
  string actor = requireString(value,"candidateActor");
  if(actor == "BLACK")
    return P_BLACK;
  if(actor == "WHITE")
    return P_WHITE;
  failFrame("candidateActor must be BLACK or WHITE");
}

json playerJson(Player player) {
  if(player == P_BLACK)
    return "BLACK";
  if(player == P_WHITE)
    return "WHITE";
  if(player == C_EMPTY)
    return nullptr;
  throw StringError("Unexpected player in Collapse Go slice projection");
}

string phaseString(CollapseGoPhase phase) {
  switch(phase) {
  case CollapseGoPhase::COLLAPSE_PLAY: return "COLLAPSE_PLAY";
  case CollapseGoPhase::ORDINARY_PLAY: return "ORDINARY_PLAY";
  case CollapseGoPhase::TERMINAL: return "TERMINAL";
  default:
    throw StringError("Unexpected Collapse Go phase in slice projection");
  }
}

string settlementReasonString(CollapseGoSettlementReason reason) {
  switch(reason) {
  case CollapseGoSettlementReason::NONE: return "NONE";
  case CollapseGoSettlementReason::THRESHOLD: return "THRESHOLD";
  case CollapseGoSettlementReason::PRE_THRESHOLD_TWO_PASSES: return "PRE_THRESHOLD_TWO_PASSES";
  default:
    throw StringError("Unexpected settlement reason in slice projection");
  }
}

json occupancyJson(const PositionalSuperkoKey& key) {
  json black = json::array();
  json white = json::array();
  const vector<uint8_t>& occupancy = key.getOccupancy();
  for(size_t point = 0; point < occupancy.size(); point++) {
    if(occupancy[point] == C_BLACK)
      black.push_back(static_cast<int>(point));
    else if(occupancy[point] == C_WHITE)
      white.push_back(static_cast<int>(point));
    else if(occupancy[point] != C_EMPTY)
      throw StringError("Unexpected occupancy color in positional-superko projection");
  }
  return json{{"black",black},{"white",white}};
}

json boardOccupancyJson(const Board& board) {
  return occupancyJson(PositionalSuperkoKey(board));
}

json quotaVectorJson(const CollapseGoState& state, Player player) {
  return json{
    {"doubleStart",state.getRemainingQuota(player,CollapseGoAbility::DOUBLE_MOVE)},
    {"eightway",state.getRemainingQuota(player,CollapseGoAbility::EIGHTWAY)},
    {"immortal",state.getRemainingQuota(player,CollapseGoAbility::IMMORTAL)},
  };
}

json remainingQuotasJson(const CollapseGoState& state) {
  return json{
    {"black",quotaVectorJson(state,P_BLACK)},
    {"white",quotaVectorJson(state,P_WHITE)},
  };
}

json pskHistoryJson(const CollapseGoState& state) {
  json history = json::array();
  const PositionalSuperkoHistory& psk = state.getPositionalSuperkoHistory();
  for(size_t i = 0; i < psk.size(); i++)
    history.push_back(occupancyJson(psk.at(i)));
  return history;
}

json scoreJson(const CollapseGoScore& score) {
  return json{
    {"blackEmptyArea",score.blackTerritory},
    {"blackScoreNumerator",score.blackScoreNumerator},
    {"blackStones",score.blackStones},
    {"denominator",2},
    {"isScored",score.isScored},
    {"marginNumerator",score.marginNumerator},
    {"whiteEmptyArea",score.whiteTerritory},
    {"whiteScoreNumerator",score.whiteScoreNumerator},
    {"whiteStones",score.whiteStones},
    {"winner",playerJson(score.winner)},
  };
}

json capturesJson(const CollapseGoApplyResult& result, Player candidateActor, int boardSize) {
  json black = json::array();
  json white = json::array();
  if(result.accepted) {
    json* captured = candidateActor == P_BLACK ? &white : &black;
    for(Loc loc: result.capturedStones) {
      int x = Location::getX(loc,boardSize);
      int y = Location::getY(loc,boardSize);
      captured->push_back(y * boardSize + x);
    }
  }
  return json{{"black",black},{"white",white}};
}

json observationJson(
  size_t stepIndex,
  const CollapseGoState& state,
  const CollapseGoApplyResult& result,
  Player candidateActor
) {
  string status;
  if(result.accepted)
    status = "ACCEPTED";
  else if(result.isUnsupportedBySlice())
    status = "UNSUPPORTED";
  else
    status = "REJECTED";

  json occupancy = boardOccupancyJson(state.getBoard());
  return json{
    {"A",state.getAtomicActionCount()},
    {"actor",playerJson(state.getActor())},
    {"blackOccupancy",occupancy.at("black")},
    {"captures",capturesJson(result,candidateActor,state.getConfig().getBoardSize())},
    {"consecutivePasses",state.getConsecutivePasses()},
    {"errorCode",result.getErrorCode()},
    {"phase",phaseString(state.getPhase())},
    {"pskHistory",pskHistoryJson(state)},
    {"remainingQuotas",remainingQuotasJson(state)},
    {"score",scoreJson(state.getScore())},
    {"settlementReason",settlementReasonString(result.settlementReason)},
    {"status",status},
    {"stepIndex",static_cast<int64_t>(stepIndex)},
    {"terminalScoring",result.terminalScoreEventEmitted},
    {"whiteOccupancy",occupancy.at("white")},
  };
}

CollapseGoConfig parseConfig(const json& request) {
  int boardSize = requireInt(request.at("boardSize"),"boardSize");
  if(!GameAction::isSupportedBoardSize(boardSize))
    failFrame("boardSize must be exactly 9, 13, or 19");

  string quotaMode = requireString(request.at("quotaMode"),"quotaMode");
  if(quotaMode == "ZERO")
    return CollapseGoConfig::allZero(boardSize);
  if(quotaMode == "ONE")
    return CollapseGoConfig::allOne(boardSize);
  failFrame("quotaMode must be ZERO or ONE");
}

json processFrame(const string& line) {
  json request = RulesetIdentity::parseRestrictedJson(line);
  if(RulesetIdentity::canonicalizeRestrictedJson(request).size() > MAX_REQUEST_FRAME_BYTES)
    failFrame("canonical request exceeds the 1 MiB request limit");
  requireExactFields(
    request,
    {"protocolVersion","episodeId","boardSize","quotaMode","steps"},
    "episode request"
  );

  string protocolVersion = requireString(request.at("protocolVersion"),"protocolVersion");
  if(protocolVersion != PROTOCOL_VERSION)
    failFrame("protocolVersion must be " + PROTOCOL_VERSION);

  string episodeId = requireString(request.at("episodeId"),"episodeId");
  validateEpisodeId(episodeId);
  CollapseGoState state(parseConfig(request));

  const json& steps = request.at("steps");
  if(!steps.is_array() || steps.empty() || steps.size() > MAX_EPISODE_STEPS)
    failFrame("steps must be a nonempty array within the test-only resource limit");

  json observations = json::array();
  for(size_t i = 0; i < steps.size(); i++) {
    const json& step = steps.at(i);
    requireExactFields(step,{"candidateActor","action"},"step " + Global::sizeToString(i));
    Player candidateActor = parseCandidateActor(step.at("candidateActor"));

    GameAction action = GameAction::ofJson(step.at("action"));
    CollapseGoApplyResult result = CollapseGoReducer::apply(state,candidateActor,action);
    state.checkConsistency();
    observations.push_back(observationJson(i,state,result,candidateActor));
  }

  return json{
    {"episodeId",episodeId},
    {"observations",observations},
    {"protocolVersion",PROTOCOL_VERSION},
  };
}

}

int main() {
  try {
#ifdef _WIN32
    if(_setmode(_fileno(stdin),_O_BINARY) == -1)
      throw IOError("Could not switch differential probe stdin to binary mode");
    if(_setmode(_fileno(stdout),_O_BINARY) == -1)
      throw IOError("Could not switch differential probe stdout to binary mode");
#endif
    Board::initHash();
    string line;
    line.reserve(MAX_REQUEST_FRAME_BYTES);
    size_t lineNumber = 1;
    while(readBoundedLine(cin,line,lineNumber)) {
      if(line.empty())
        failFrame("line " + Global::sizeToString(lineNumber) + " is empty");
      json response = processFrame(line);
      string responseLine = RulesetIdentity::canonicalizeRestrictedJson(response);
      if(responseLine.size() > MAX_RESPONSE_FRAME_BYTES)
        failFrame("response exceeds the 16 MiB response limit");
      cout << responseLine << '\n';
      if(!cout)
        throw IOError("Could not write differential probe response");
      lineNumber++;
    }
    return 0;
  }
  catch(const exception& e) {
    cerr << "mutago-collapse-slice-probe: " << e.what() << endl;
    return 2;
  }
}
