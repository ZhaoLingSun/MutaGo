// Test-only differential probe for explicitly UNFROZEN Collapse Go slices.

#include <algorithm>
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
#include "../game/collapsegotopology.h"
#include "../game/gameaction.h"
#include "../game/rulesetidentity.h"

using nlohmann::json;
using namespace std;

namespace {

const string LEGACY_PROTOCOL_VERSION = "normal-pass-diff-v0-unfrozen";
const string DOUBLE_PROTOCOL_VERSION = "double-move-diff-v1-unfrozen";
constexpr size_t MAX_REQUEST_FRAME_BYTES = 1024 * 1024;
constexpr size_t MAX_LEGACY_RESPONSE_FRAME_BYTES = 16 * 1024 * 1024;
constexpr size_t MAX_DOUBLE_RESPONSE_FRAME_BYTES = 32 * 1024 * 1024;
constexpr size_t MAX_EPISODE_STEPS = 160;
constexpr int MAX_TEST_QUOTA = 4;

[[noreturn]] void failFrame(const string& message) {
  // Retain the legacy diagnostic prefix for backward-compatible malformed-frame tests.
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

string actionKindString(GameActionKind kind) {
  switch(kind) {
  case GameActionKind::NORMAL: return "NORMAL";
  case GameActionKind::IMMORTAL: return "IMMORTAL";
  case GameActionKind::DOUBLE_START: return "DOUBLE_START";
  case GameActionKind::EIGHTWAY: return "EIGHTWAY";
  case GameActionKind::PASS: return "PASS";
  default:
    throw StringError("Unexpected action kind in Collapse Go projection");
  }
}

string abilityStateString(CollapseGoLedgerAbilityState state) {
  switch(state) {
  case CollapseGoLedgerAbilityState::CONSUMED: return "CONSUMED";
  case CollapseGoLedgerAbilityState::INACTIVE: return "INACTIVE";
  default:
    throw StringError("Unexpected ledger ability state");
  }
}

string stoneStateString(CollapseGoLedgerStoneState state) {
  switch(state) {
  case CollapseGoLedgerStoneState::ON_BOARD: return "ON_BOARD";
  case CollapseGoLedgerStoneState::CAPTURED: return "CAPTURED";
  default:
    throw StringError("Unexpected ledger stone state");
  }
}

string ledgerSettlementStateString(CollapseGoLedgerSettlementState state) {
  switch(state) {
  case CollapseGoLedgerSettlementState::PENDING: return "PENDING";
  case CollapseGoLedgerSettlementState::SETTLED: return "SETTLED";
  default:
    throw StringError("Unexpected ledger settlement state");
  }
}

string actionEventId(int64_t actionNumber) {
  return "action-" + to_string(actionNumber);
}

string specialEventId(int64_t specialLink) {
  return "special-" + to_string(specialLink);
}

string stoneSourceId(int64_t originActionNumber) {
  return "stone-" + to_string(originActionNumber);
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

json positionOccupancyJson(const CollapseGoPosition& position) {
  return occupancyJson(PositionalSuperkoKey(position.getBoardSize(),position.getRowMajorOccupancy()));
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
  vector<int> points;
  if(result.accepted) {
    for(Loc loc: result.capturedStones) {
      int x = Location::getX(loc,boardSize);
      int y = Location::getY(loc,boardSize);
      points.push_back(y * boardSize + x);
    }
    sort(points.begin(),points.end());
  }
  json black = json::array();
  json white = json::array();
  json* captured = candidateActor == P_BLACK ? &white : &black;
  for(int point: points)
    captured->push_back(point);
  return json{{"black",black},{"white",white}};
}

json legacyObservationJson(
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

  json occupancy = positionOccupancyJson(state.getPosition());
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

CollapseGoConfig parseLegacyConfig(const json& request) {
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

CollapseGoApplyResult unsupportedResult() {
  CollapseGoApplyResult result;
  result.accepted = false;
  result.error = CollapseGoApplyError::UNSUPPORTED_BY_SLICE;
  return result;
}

CollapseGoApplyResult applyLegacyV0(
  CollapseGoState& state,
  Player candidateActor,
  const GameAction& action
) {
  CollapseGoState candidate(state);
  CollapseGoApplyResult result = CollapseGoReducer::apply(candidate,candidateActor,action);
  const GameActionKind kind = action.getKind();
  const bool special = kind == GameActionKind::IMMORTAL ||
    kind == GameActionKind::DOUBLE_START || kind == GameActionKind::EIGHTWAY;
  if(result.accepted && special)
    return unsupportedResult();
  if(result.accepted)
    state = candidate;
  return result;
}

json processLegacyRequest(const json& request) {
  requireExactFields(
    request,
    {"protocolVersion","episodeId","boardSize","quotaMode","steps"},
    "episode request"
  );
  if(requireString(request.at("protocolVersion"),"protocolVersion") != LEGACY_PROTOCOL_VERSION)
    failFrame("protocolVersion must be " + LEGACY_PROTOCOL_VERSION);

  string episodeId = requireString(request.at("episodeId"),"episodeId");
  validateEpisodeId(episodeId);
  CollapseGoState state(parseLegacyConfig(request));

  const json& steps = request.at("steps");
  if(!steps.is_array() || steps.empty() || steps.size() > MAX_EPISODE_STEPS)
    failFrame("steps must be a nonempty array within the test-only resource limit");

  json observations = json::array();
  for(size_t i = 0; i < steps.size(); i++) {
    const json& step = steps.at(i);
    requireExactFields(step,{"candidateActor","action"},"step " + Global::sizeToString(i));
    Player candidateActor = parseCandidateActor(step.at("candidateActor"));
    GameAction action = GameAction::ofJson(step.at("action"));
    CollapseGoApplyResult result = applyLegacyV0(state,candidateActor,action);
    state.checkConsistency();
    observations.push_back(legacyObservationJson(i,state,result,candidateActor));
  }

  return json{
    {"episodeId",episodeId},
    {"observations",observations},
    {"protocolVersion",LEGACY_PROTOCOL_VERSION},
  };
}

enum class QuotaBucket {
  INITIAL,
  REMAINING,
  USED,
  EXPIRED,
};

int64_t quotaValue(
  const CollapseGoState& state,
  Player player,
  CollapseGoAbility ability,
  QuotaBucket bucket
) {
  switch(bucket) {
  case QuotaBucket::INITIAL: return state.getInitialQuota(player,ability);
  case QuotaBucket::REMAINING: return state.getRemainingQuota(player,ability);
  case QuotaBucket::USED: return state.getUsedQuota(player,ability);
  case QuotaBucket::EXPIRED: return state.getExpiredQuota(player,ability);
  default:
    throw StringError("Unexpected quota bucket");
  }
}

json exactQuotaVectorJson(const CollapseGoState& state, Player player, QuotaBucket bucket) {
  return json{
    {"DOUBLE_START",quotaValue(state,player,CollapseGoAbility::DOUBLE_MOVE,bucket)},
    {"EIGHTWAY",quotaValue(state,player,CollapseGoAbility::EIGHTWAY,bucket)},
    {"IMMORTAL",quotaValue(state,player,CollapseGoAbility::IMMORTAL,bucket)},
  };
}

json exactPlayerQuotasJson(const CollapseGoState& state, QuotaBucket bucket) {
  return json{
    {"BLACK",exactQuotaVectorJson(state,P_BLACK,bucket)},
    {"WHITE",exactQuotaVectorJson(state,P_WHITE,bucket)},
  };
}

json rationalJson(int numerator) {
  return json{{"denominator",2},{"numerator",numerator}};
}

json terminalStateJson(const CollapseGoState& state) {
  const CollapseGoScore& score = state.getScore();
  if(!score.isScored)
    return json{{"ended",false}};
  Player winner = score.winner;
  return json{
    {"ended",true},
    {"loser",playerJson(getOpp(winner))},
    {"reason","SCORE"},
    {"score",json{
      {"black",rationalJson(score.blackScoreNumerator)},
      {"margin",rationalJson(score.marginNumerator)},
      {"white",rationalJson(score.whiteScoreNumerator)},
    }},
    {"winner",playerJson(winner)},
  };
}

json stonesJson(const CollapseGoPosition& position) {
  json stones = json::array();
  for(int point = 0; point < position.getPointCount(); point++) {
    const CollapseGoCell& cell = position.getCell(point);
    if(!cell.isOccupied())
      continue;
    const CollapseGoStoneSource& source = cell.getSource();
    json special = source.specialLink.has_value() ? json(specialEventId(*source.specialLink)) : json(nullptr);
    stones.push_back(json{
      {"color",playerJson(cell.getColor())},
      {"originActionNumber",source.originActionNumber},
      {"originKind",actionKindString(source.originKind)},
      {"point",point},
      {"sourceId",stoneSourceId(source.originActionNumber)},
      {"specialEventId",special},
    });
  }
  return stones;
}

json ledgerJson(const CollapseGoState& state) {
  json ledger = json::array();
  for(size_t i = 0; i < state.getLedger().size(); i++) {
    const CollapseGoLedgerEntry& entry = state.getLedger().at(i);
    ledger.push_back(json{
      {"abilityState",abilityStateString(entry.abilityState)},
      {"eventId",specialEventId(entry.specialLink)},
      {"kind",actionKindString(entry.originKind)},
      {"logicalOrder",entry.originActionNumber - 1},
      {"originActionNumber",entry.originActionNumber},
      {"owner",playerJson(entry.owner)},
      {"settlementState",ledgerSettlementStateString(entry.settlementState)},
      {"sourcePoint",entry.sourcePoint},
      {"sourceStoneId",stoneSourceId(entry.originActionNumber)},
      {"stoneState",stoneStateString(entry.stoneState)},
      {"tombstone",entry.tombstone},
    });
  }
  return ledger;
}

json pendingDoubleJson(const CollapseGoState& state) {
  if(!state.getPendingDouble().has_value())
    return nullptr;
  const CollapseGoPendingDouble& pending = *state.getPendingDouble();
  return json{
    {"eventId",specialEventId(pending.specialLink)},
    {"owner",playerJson(pending.owner)},
    {"startActionNumber",pending.originActionNumber},
  };
}

json groupsJson(const CollapseGoState& state) {
  CollapseGoTopology topology = CollapseGoTopology::fullScanN4(state.getPosition());
  json groups = json::array();
  for(const CollapseGoGroup& group: topology.getGroups()) {
    groups.push_back(json{
      {"color",playerJson(group.color)},
      {"eightwayAnchors",json::array()},
      {"immortalAnchors",json::array()},
      {"liberties",group.liberties},
      {"protected",false},
      {"stones",group.stones},
    });
  }
  return groups;
}

json exactStateJson(const CollapseGoState& state) {
  return json{
    {"actor",playerJson(state.getActor())},
    {"atomicActionCount",state.getAtomicActionCount()},
    {"boardSize",state.getConfig().getBoardSize()},
    {"consecutivePasses",state.getConsecutivePasses()},
    {"expiredQuotas",exactPlayerQuotasJson(state,QuotaBucket::EXPIRED)},
    {"groups",groupsJson(state)},
    {"initialQuotas",exactPlayerQuotasJson(state,QuotaBucket::INITIAL)},
    {"ledger",ledgerJson(state)},
    {"logPosition",state.getLogPosition()},
    {"occupancy",positionOccupancyJson(state.getPosition())},
    {"pendingDouble",pendingDoubleJson(state)},
    {"phase",phaseString(state.getPhase())},
    {"pskHistory",pskHistoryJson(state)},
    {"remainingQuotas",exactPlayerQuotasJson(state,QuotaBucket::REMAINING)},
    {"revision",state.getRevision()},
    {"settledLedgerCount",state.getSettledLedgerCount()},
    {"settlementCompleted",state.isSettlementCompleted()},
    {"stableTerminalEventCount",state.getStableTerminalEventCount()},
    {"stones",stonesJson(state.getPosition())},
    {"terminal",terminalStateJson(state)},
    {"threshold",state.getConfig().getThreshold()},
    {"usedQuotas",exactPlayerQuotasJson(state,QuotaBucket::USED)},
  };
}

json atomicEventJson(
  const CollapseGoState& before,
  const CollapseGoState& after,
  const CollapseGoApplyResult& result,
  Player candidateActor,
  const json& actionJson
) {
  if(!result.accepted)
    return nullptr;
  const int64_t actionNumber = after.getAtomicActionCount();
  return json{
    {"action",actionJson},
    {"actionNumber",actionNumber},
    {"actor",playerJson(candidateActor)},
    {"captured",capturesJson(result,candidateActor,after.getConfig().getBoardSize())},
    {"eventId",actionEventId(actionNumber)},
    {"pskHistoryIndex",static_cast<int64_t>(before.getPositionalSuperkoHistory().size())},
    {"stableOccupancy",positionOccupancyJson(after.getPosition())},
  };
}

json settlementTraceJson(
  const CollapseGoState& before,
  const CollapseGoState& after,
  const CollapseGoApplyResult& result
) {
  if(!result.settlementTriggered)
    return nullptr;
  json steps = json::array();
  const int64_t atomicPskIndex = static_cast<int64_t>(before.getPositionalSuperkoHistory().size());
  for(size_t i = 0; i < result.settlementSteps.size(); i++) {
    const CollapseGoSettlementStep& step = result.settlementSteps[i];
    steps.push_back(json{
      {"abilityDeactivated",step.abilityDeactivated},
      {"ledgerEventId",specialEventId(step.specialLink)},
      {"noOp",step.noOp},
      {"pskHistoryIndex",atomicPskIndex + 1 + static_cast<int64_t>(i)},
      {"removalBatches",json::array()},
      {"stableOccupancy",positionOccupancyJson(after.getPosition())},
      {"stepIndex",static_cast<int64_t>(i)},
    });
  }
  return json{
    {"handoffActor",playerJson(after.getActor())},
    {"steps",steps},
    {"triggerReason",settlementReasonString(result.settlementReason)},
  };
}

json terminalEventJson(
  const CollapseGoState& after,
  const CollapseGoApplyResult& result
) {
  if(!result.terminalScoreEventEmitted)
    return nullptr;
  const CollapseGoScore& score = after.getScore();
  return json{
    {"eventId","terminal-" + to_string(after.getLogPosition())},
    {"loser",playerJson(getOpp(score.winner))},
    {"pskHistoryIndex",static_cast<int64_t>(after.getPositionalSuperkoHistory().size() - 1)},
    {"reason","SCORE"},
    {"stableOccupancy",positionOccupancyJson(after.getPosition())},
    {"winner",playerJson(score.winner)},
  };
}

json exactTransitionJson(
  const CollapseGoState& before,
  const CollapseGoState& after,
  const CollapseGoApplyResult& result,
  Player candidateActor,
  const json& actionJson
) {
  string status = result.accepted ? "ACCEPTED" :
    result.isUnsupportedBySlice() ? "UNSUPPORTED" : "REJECTED";
  string transitionKind = result.accepted ? "ATOMIC_ACTION" :
    result.isUnsupportedBySlice() ? "UNSUPPORTED" : "REJECTED";
  json errorCode = result.accepted ? json(nullptr) : json(result.getErrorCode());
  return json{
    {"accepted",result.accepted},
    {"action",actionJson},
    {"atomicEvent",atomicEventJson(before,after,result,candidateActor,actionJson)},
    {"candidateActor",playerJson(candidateActor)},
    {"errorCode",errorCode},
    {"positionalSuperkoAppends",result.positionalSuperkoAppends},
    {"settlement",settlementTraceJson(before,after,result)},
    {"status",status},
    {"terminalEvent",terminalEventJson(after,result)},
    {"transitionKind",transitionKind},
  };
}

CollapseGoQuotas parseQuotaVector(const json& value, const string& context) {
  requireExactFields(value,{"IMMORTAL","DOUBLE_START","EIGHTWAY"},context);
  int immortal = requireInt(value.at("IMMORTAL"),context + ".IMMORTAL");
  int doubleMove = requireInt(value.at("DOUBLE_START"),context + ".DOUBLE_START");
  int eightway = requireInt(value.at("EIGHTWAY"),context + ".EIGHTWAY");
  for(const pair<string,int>& quota: {
    make_pair(string("IMMORTAL"),immortal),
    make_pair(string("DOUBLE_START"),doubleMove),
    make_pair(string("EIGHTWAY"),eightway),
  }) {
    if(quota.second < 0 || quota.second > MAX_TEST_QUOTA)
      failFrame(context + "." + quota.first + " must be in 0..4 for this bounded test carrier");
  }
  return CollapseGoQuotas(immortal,doubleMove,eightway);
}

CollapseGoConfig parseDoubleConfig(const json& request) {
  int boardSize = requireInt(request.at("boardSize"),"boardSize");
  if(!GameAction::isSupportedBoardSize(boardSize))
    failFrame("boardSize must be exactly 9, 13, or 19");
  const json& quotas = request.at("initialQuotas");
  requireExactFields(quotas,{"BLACK","WHITE"},"initialQuotas");
  return CollapseGoConfig(
    boardSize,
    parseQuotaVector(quotas.at("BLACK"),"initialQuotas.BLACK"),
    parseQuotaVector(quotas.at("WHITE"),"initialQuotas.WHITE")
  );
}

json processDoubleRequest(const json& request) {
  requireExactFields(
    request,
    {"protocolVersion","episodeId","boardSize","initialQuotas","steps"},
    "Double episode request"
  );
  if(requireString(request.at("protocolVersion"),"protocolVersion") != DOUBLE_PROTOCOL_VERSION)
    failFrame("protocolVersion must be " + DOUBLE_PROTOCOL_VERSION);

  string episodeId = requireString(request.at("episodeId"),"episodeId");
  validateEpisodeId(episodeId);
  CollapseGoState state(parseDoubleConfig(request));
  json initialState = exactStateJson(state);

  const json& steps = request.at("steps");
  if(!steps.is_array() || steps.empty() || steps.size() > MAX_EPISODE_STEPS)
    failFrame("steps must be a nonempty array within the test-only resource limit");

  json observations = json::array();
  for(size_t i = 0; i < steps.size(); i++) {
    const json& step = steps.at(i);
    requireExactFields(step,{"candidateActor","action"},"Double step " + Global::sizeToString(i));
    Player candidateActor = parseCandidateActor(step.at("candidateActor"));
    GameAction action = GameAction::ofJson(step.at("action"));
    CollapseGoState before(state);
    CollapseGoApplyResult result = CollapseGoReducer::apply(state,candidateActor,action);
    state.checkConsistency();
    observations.push_back(json{
      {"state",exactStateJson(state)},
      {"stepIndex",static_cast<int64_t>(i + 1)},
      {"transition",exactTransitionJson(before,state,result,candidateActor,step.at("action"))},
    });
  }

  return json{
    {"episodeId",episodeId},
    {"initialState",initialState},
    {"observations",observations},
    {"protocolVersion",DOUBLE_PROTOCOL_VERSION},
  };
}

json processFrame(const string& line) {
  json request = RulesetIdentity::parseRestrictedJson(line);
  if(RulesetIdentity::canonicalizeRestrictedJson(request).size() > MAX_REQUEST_FRAME_BYTES)
    failFrame("canonical request exceeds the 1 MiB request limit");
  if(!request.is_object() || request.find("protocolVersion") == request.end())
    failFrame("episode request must contain protocolVersion");
  string protocolVersion = requireString(request.at("protocolVersion"),"protocolVersion");
  if(protocolVersion == LEGACY_PROTOCOL_VERSION)
    return processLegacyRequest(request);
  if(protocolVersion == DOUBLE_PROTOCOL_VERSION)
    return processDoubleRequest(request);
  failFrame("unsupported protocolVersion " + protocolVersion);
}

size_t responseLimit(const json& response) {
  if(response.at("protocolVersion") == DOUBLE_PROTOCOL_VERSION)
    return MAX_DOUBLE_RESPONSE_FRAME_BYTES;
  return MAX_LEGACY_RESPONSE_FRAME_BYTES;
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
      if(responseLine.size() > responseLimit(response))
        failFrame("response exceeds the protocol-specific response limit");
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
