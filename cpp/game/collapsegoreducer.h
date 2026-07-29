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
  DOUBLE_THRESHOLD,
  QUOTA_EXHAUSTED,
  POINT_OCCUPIED,
  SUICIDE,
  POSITIONAL_SUPERKO,
  INTERNAL_INVARIANT,
  UNSUPPORTED_BY_SLICE,
};

struct CollapseGoApplyResult {
  bool accepted;
  CollapseGoApplyError error;
  std::vector<Loc> capturedStones;
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
  static void completeEmptyLedgerSettlement(
    CollapseGoState& state,
    CollapseGoSettlementReason reason,
    CollapseGoApplyResult& result
  );
  static CollapseGoScore scoreChineseArea(const CollapseGoPosition& position);
};

#endif // GAME_COLLAPSEGOREDUCER_H_
