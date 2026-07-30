#ifndef GAME_COLLAPSEGOREDUCER_H_
#define GAME_COLLAPSEGOREDUCER_H_

#include <string>
#include <vector>

#include "../game/collapsegostate.h"
#include "../game/gameaction.h"

enum class CollapseGoApplyError {
  NONE,
  POINT_OFF_BOARD,
  TERMINAL_STATE,
  INVALID_PHASE,
  WRONG_ACTOR,
  DOUBLE_CONTINUATION_KIND_FORBIDDEN,
  DOUBLE_THRESHOLD,
  QUOTA_EXHAUSTED,
  POINT_OCCUPIED,
  SUICIDE,
  POSITIONAL_SUPERKO,
  INTERNAL_INVARIANT,
  UNSUPPORTED_BY_SLICE,
};

struct CollapseGoRemovalBatch {
  std::vector<Loc> blackStones;
  std::vector<Loc> whiteStones;

  bool operator==(const CollapseGoRemovalBatch& other) const;
  bool operator!=(const CollapseGoRemovalBatch& other) const;
};

struct CollapseGoSettlementStep {
  int64_t stepIndex;
  int64_t specialLink;
  int64_t originActionNumber;
  Player owner;
  GameActionKind originKind;
  int sourcePoint;
  bool noOp;
  bool abilityDeactivated;
  std::vector<CollapseGoRemovalBatch> removalBatches;
  std::vector<uint8_t> stableOccupancy;
  int64_t positionalSuperkoHistoryIndex;

  CollapseGoSettlementStep(const CollapseGoLedgerEntry& entry, int64_t settlementStepIndex);

  bool operator==(const CollapseGoSettlementStep& other) const;
  bool operator!=(const CollapseGoSettlementStep& other) const;
};

struct CollapseGoApplyResult {
  bool accepted;
  CollapseGoApplyError error;
  std::vector<Loc> capturedStones;
  std::vector<CollapseGoSettlementStep> settlementSteps;
  bool settlementTriggered;
  CollapseGoSettlementReason settlementReason;
  bool terminalScoreEventEmitted;
  int positionalSuperkoAppends;

  CollapseGoApplyResult();

  bool isSemanticRejection() const;
  bool isUnsupportedBySlice() const;
  std::string getErrorCode() const;
};

class CollapseGoReducer {
public:
  static CollapseGoApplyResult apply(CollapseGoState& state, Player actor, const GameAction& action);

private:
  static CollapseGoApplyResult reject(CollapseGoApplyError error);
  static CollapseGoAbility abilityForAction(GameActionKind kind);
  static void appendOccupancy(CollapseGoState& state, const std::vector<uint8_t>& occupancy);
  static void appendCurrentOccupancy(CollapseGoState& state);
  static void markCapturedSpecialSources(
    CollapseGoState& state,
    const CollapseGoPosition& previousPosition,
    const std::vector<int>& capturedPoints
  );
  static void completeLedgerSettlement(
    CollapseGoState& state,
    CollapseGoSettlementReason reason,
    CollapseGoApplyResult& result
  );
  static void completeSettlementIfTriggered(CollapseGoState& state, CollapseGoApplyResult& result);
  static CollapseGoScore scoreChineseArea(const CollapseGoPosition& position);
};

#endif // GAME_COLLAPSEGOREDUCER_H_
