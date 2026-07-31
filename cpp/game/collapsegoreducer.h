#ifndef GAME_COLLAPSEGOREDUCER_H_
#define GAME_COLLAPSEGOREDUCER_H_

#include <bitset>
#include <optional>
#include <string>
#include <vector>

#include "../game/collapsegostate.h"
#include "../game/gameaction.h"

class CollapseGoReducerTestAccess;

enum class CollapseGoApplyError {
  NONE,
  POINT_OFF_BOARD,
  TERMINAL_STATE,
  INVALID_PHASE,
  INVALID_LOSER,
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

struct CollapseGoTerminalEvent {
  CollapseGoTerminalReason reason;
  Player winner;
  Player loser;
  CollapseGoScore score;
  bool settlementCompleted;
  CollapseGoPosition stablePosition;
  std::vector<uint8_t> stableOccupancy;
  int64_t positionalSuperkoHistoryIndex;
  int64_t revision;
  int64_t logPosition;

  CollapseGoTerminalEvent(const CollapseGoTerminalEvent&) = default;
  CollapseGoTerminalEvent(CollapseGoTerminalEvent&&) = default;
  CollapseGoTerminalEvent& operator=(const CollapseGoTerminalEvent&) = default;
  CollapseGoTerminalEvent& operator=(CollapseGoTerminalEvent&&) = default;

  static CollapseGoTerminalEvent fromCommittedState(const CollapseGoState& committedState);
  void validateAgainstCommittedState(const CollapseGoState& committedState) const;

  bool operator==(const CollapseGoTerminalEvent& other) const;
  bool operator!=(const CollapseGoTerminalEvent& other) const;

private:
  explicit CollapseGoTerminalEvent(const CollapseGoState& committedState);
};

struct CollapseGoApplyResult {
  bool accepted;
  CollapseGoApplyError error;
  std::vector<Loc> capturedStones;
  std::optional<CollapseGoState> atomicStateSnapshot;
  std::vector<CollapseGoSettlementStep> settlementSteps;
  bool settlementTriggered;
  CollapseGoSettlementReason settlementReason;
  std::optional<CollapseGoTerminalEvent> terminalEvent;
  bool terminalScoreEventEmitted;
  int positionalSuperkoAppends;

  CollapseGoApplyResult();

  bool isSemanticRejection() const;
  bool isUnsupportedBySlice() const;
  std::string getErrorCode() const;
};

using CollapseGoLegalMask = std::bitset<GameAction::FLAT_ACTION_COUNT>;

class CollapseGoReducer {
public:
  [[nodiscard]] static CollapseGoLegalMask deriveLegalMask(const CollapseGoState& state);
  static CollapseGoApplyResult apply(CollapseGoState& state, Player actor, const GameAction& action);
  static CollapseGoApplyResult terminate(
    CollapseGoState& state,
    Player loser,
    CollapseGoAdministrativeTerminationReason reason
  );

private:
  struct LegalityContext;
  struct PreparedPlacement;
  struct PreparedAction;

  static CollapseGoApplyResult reject(CollapseGoApplyError error);
  static CollapseGoAbility abilityForAction(GameActionKind kind);
  static LegalityContext buildLegalityContext(const CollapseGoState& state);
  static PreparedAction prepareAction(
    const CollapseGoState& state,
    const LegalityContext& context,
    Player actor,
    const GameAction& action
  );
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

  friend class CollapseGoReducerTestAccess;
};

#endif // GAME_COLLAPSEGOREDUCER_H_
