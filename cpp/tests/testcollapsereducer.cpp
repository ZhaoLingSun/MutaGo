#include "../tests/tests.h"

#include <algorithm>
#include <limits>
#include <type_traits>

#include "../game/collapsegoreducer.h"
#include "../game/collapsegotopology.h"

using namespace std;

class CollapseGoStateTestAccess {
public:
  static CollapseGoLedgerEntry& ledgerEntry(CollapseGoState& state, size_t index) {
    return state.ledger.entries.at(index);
  }

  static void clearPendingDouble(CollapseGoState& state) {
    state.pendingDouble.reset();
  }

  static void setPendingDouble(
    CollapseGoState& state,
    Player owner,
    int64_t specialLink,
    int64_t originActionNumber
  ) {
    state.pendingDouble = CollapseGoPendingDouble(owner,specialLink,originActionNumber);
  }

  static void setPhase(CollapseGoState& state, CollapseGoPhase phase) {
    state.phase = phase;
  }

  static void setActor(CollapseGoState& state, Player actor) {
    state.actor = actor;
  }

  static void setRevision(CollapseGoState& state, int64_t revision) {
    state.revision = revision;
  }

  static void setAtomicActionCount(CollapseGoState& state, int64_t actionCount) {
    state.atomicActionCount = actionCount;
  }

  static void setConsecutivePasses(CollapseGoState& state, int64_t passCount) {
    state.consecutivePasses = passCount;
  }

  static void setLogPosition(CollapseGoState& state, int64_t logPosition) {
    state.logPosition = logPosition;
  }

  static void setSettlementCompleted(CollapseGoState& state, bool completed) {
    state.settlementCompleted = completed;
  }

  static void resetPskToRepeatedCurrent(CollapseGoState& state, size_t count) {
    if(count == 0)
      throw StringError("Collapse Go test PSK reset requires the initial seed");
    PositionalSuperkoHistory replacement(state.positionalSuperkoHistory.at(0));
    PositionalSuperkoKey current(
      state.position.getBoardSize(),state.position.getRowMajorOccupancy()
    );
    for(size_t index = 1; index < count; index++)
      replacement.append(current);
    state.positionalSuperkoHistory = replacement;
  }

  static void swapStoneSources(CollapseGoState& state, int firstPoint, int secondPoint) {
    const CollapseGoCell firstCell = state.position.getCell(firstPoint);
    const CollapseGoCell secondCell = state.position.getCell(secondPoint);
    if(!firstCell.isOccupied() || !secondCell.isOccupied())
      throw StringError("Collapse Go source swap requires two occupied points");
    const Color firstColor = firstCell.getColor();
    const Color secondColor = secondCell.getColor();
    const CollapseGoStoneSource firstSource = firstCell.getSource();
    const CollapseGoStoneSource secondSource = secondCell.getSource();
    state.position.removeStone(firstPoint);
    state.position.removeStone(secondPoint);
    state.position.placeStone(firstPoint,firstColor,secondSource);
    state.position.placeStone(secondPoint,secondColor,firstSource);
  }

  static void relabelStoneSource(
    CollapseGoState& state,
    int point,
    const CollapseGoStoneSource& source
  ) {
    const CollapseGoCell cell = state.position.getCell(point);
    if(!cell.isOccupied())
      throw StringError("Collapse Go source relabel requires an occupied point");
    const Color color = cell.getColor();
    state.position.removeStone(point);
    state.position.placeStone(point,color,source);
  }

  static void clearTerminalState(CollapseGoState& state) {
    state.terminalState.reset();
  }

  static CollapseGoTerminalState& terminalState(CollapseGoState& state) {
    return *state.terminalState;
  }

  static CollapseGoScore& score(CollapseGoState& state) {
    return state.score;
  }

  static void replacePskOccupancy(
    CollapseGoState& state,
    size_t index,
    const vector<uint8_t>& occupancy
  ) {
    const PositionalSuperkoHistory& history = state.positionalSuperkoHistory;
    if(index >= history.size())
      throw StringError("Collapse Go test PSK replacement index is out of range");
    PositionalSuperkoKey replacementKey(state.position.getBoardSize(),occupancy);
    PositionalSuperkoHistory replacement(index == 0 ? replacementKey : history.at(0));
    for(size_t historyIndex = 1; historyIndex < history.size(); historyIndex++)
      replacement.append(historyIndex == index ? replacementKey : history.at(historyIndex));
    state.positionalSuperkoHistory = replacement;
  }

  static void insertPskOccupancy(
    CollapseGoState& state,
    size_t index,
    const vector<uint8_t>& occupancy
  ) {
    const PositionalSuperkoHistory& history = state.positionalSuperkoHistory;
    if(index == 0 || index > history.size())
      throw StringError("Collapse Go test PSK insertion index is out of range");
    PositionalSuperkoKey insertedKey(state.position.getBoardSize(),occupancy);
    PositionalSuperkoHistory replacement(history.at(0));
    for(size_t historyIndex = 1; historyIndex < history.size(); historyIndex++) {
      if(historyIndex == index)
        replacement.append(insertedKey);
      replacement.append(history.at(historyIndex));
    }
    if(index == history.size())
      replacement.append(insertedKey);
    state.positionalSuperkoHistory = replacement;
  }

  static void appendSyntheticNormalStone(
    CollapseGoState& state,
    int x,
    int y,
    Player color
  ) {
    const int64_t actionNumber = state.atomicActionCount + 1;
    state.position.placeStone(
      x,y,color,CollapseGoStoneSource(actionNumber,GameActionKind::NORMAL,nullopt)
    );
    state.atomicActionCount++;
    state.revision++;
    state.logPosition++;
    state.consecutivePasses = 0;
    state.positionalSuperkoHistory.append(PositionalSuperkoKey(
      state.position.getBoardSize(),state.position.getRowMajorOccupancy()
    ));
  }

  static void appendSyntheticPass(CollapseGoState& state) {
    state.atomicActionCount++;
    state.revision++;
    state.logPosition++;
    state.consecutivePasses++;
    state.actor = getOpp(state.actor);
    state.positionalSuperkoHistory.append(PositionalSuperkoKey(
      state.position.getBoardSize(),state.position.getRowMajorOccupancy()
    ));
  }
};

class CollapseGoReducerTestAccess {
public:
  static CollapseGoApplyResult completeSyntheticSettlement(
    CollapseGoState& state,
    CollapseGoSettlementReason reason
  ) {
    CollapseGoApplyResult result;
    result.accepted = true;
    result.error = CollapseGoApplyError::NONE;
    CollapseGoReducer::completeLedgerSettlement(state,reason,result);
    return result;
  }
};

namespace {

GameAction normalAction(int boardSize, int x, int y) {
  return GameAction::fromBoard(GameActionKind::NORMAL,boardSize,x,y);
}

int transformPoint(int boardSize, int point, int symmetry) {
  int x = point % boardSize;
  int y = point / boardSize;
  if((symmetry & 2) != 0)
    x = boardSize - 1 - x;
  if((symmetry & 1) != 0)
    y = boardSize - 1 - y;
  if((symmetry & 4) != 0)
    swap(x,y);
  return y * boardSize + x;
}

vector<uint8_t> transformedOccupancy(
  const vector<uint8_t>& occupancy,
  int boardSize,
  int symmetry
) {
  vector<uint8_t> transformed(occupancy.size(),static_cast<uint8_t>(C_EMPTY));
  for(int point = 0; point < boardSize * boardSize; point++)
    transformed[static_cast<size_t>(transformPoint(boardSize,point,symmetry))] =
      occupancy[static_cast<size_t>(point)];
  return transformed;
}

void assertTransformedPosition(
  const CollapseGoPosition& reference,
  const CollapseGoPosition& transformed,
  int boardSize,
  int symmetry
) {
  testAssert(reference.getBoardSize() == boardSize);
  testAssert(transformed.getBoardSize() == boardSize);
  for(int point = 0; point < boardSize * boardSize; point++) {
    const CollapseGoCell& referenceCell = reference.getCell(point);
    const CollapseGoCell& transformedCell = transformed.getCell(
      transformPoint(boardSize,point,symmetry)
    );
    testAssert(referenceCell.isOccupied() == transformedCell.isOccupied());
    if(referenceCell.isOccupied()) {
      testAssert(referenceCell.getColor() == transformedCell.getColor());
      testAssert(referenceCell.getSource() == transformedCell.getSource());
    }
  }
}

vector<Loc> transformedLocs(const vector<Loc>& locs, int boardSize, int symmetry) {
  vector<Loc> transformed;
  transformed.reserve(locs.size());
  for(Loc loc: locs) {
    int point = Location::getY(loc,boardSize) * boardSize + Location::getX(loc,boardSize);
    int transformedPoint = transformPoint(boardSize,point,symmetry);
    transformed.push_back(Location::getLoc(
      transformedPoint % boardSize,transformedPoint / boardSize,boardSize
    ));
  }
  sort(transformed.begin(),transformed.end());
  return transformed;
}

vector<CollapseGoGroup> transformedGroups(
  const vector<CollapseGoGroup>& groups,
  int boardSize,
  int symmetry
) {
  vector<CollapseGoGroup> transformed = groups;
  for(CollapseGoGroup& group: transformed) {
    for(int& point: group.stones)
      point = transformPoint(boardSize,point,symmetry);
    for(int& point: group.liberties)
      point = transformPoint(boardSize,point,symmetry);
    sort(group.stones.begin(),group.stones.end());
    sort(group.liberties.begin(),group.liberties.end());
  }
  sort(transformed.begin(),transformed.end(),[](const CollapseGoGroup& left, const CollapseGoGroup& right) {
    return left.stones.front() < right.stones.front();
  });
  return transformed;
}

GameAction specialAction(GameActionKind kind, int boardSize, int x, int y) {
  return GameAction::fromBoard(kind,boardSize,x,y);
}

CollapseGoApplyResult applyAccepted(CollapseGoState& state, Player actor, const GameAction& action) {
  CollapseGoApplyResult result = CollapseGoReducer::apply(state,actor,action);
  if(!result.accepted)
    throw StringError("Expected accepted Collapse Go action, got " + result.getErrorCode());
  return result;
}

CollapseGoApplyResult playNormal(CollapseGoState& state, int x, int y) {
  return applyAccepted(
    state,
    state.getActor(),
    normalAction(state.getConfig().getBoardSize(),x,y)
  );
}

CollapseGoApplyResult playPass(CollapseGoState& state) {
  return applyAccepted(state,state.getActor(),GameAction::pass());
}

CollapseGoApplyResult playImmortal(CollapseGoState& state, int x, int y) {
  return applyAccepted(
    state,
    state.getActor(),
    specialAction(GameActionKind::IMMORTAL,state.getConfig().getBoardSize(),x,y)
  );
}

CollapseGoApplyResult playEightway(CollapseGoState& state, int x, int y) {
  return applyAccepted(
    state,
    state.getActor(),
    specialAction(GameActionKind::EIGHTWAY,state.getConfig().getBoardSize(),x,y)
  );
}

CollapseGoApplyResult playDoubleStart(CollapseGoState& state, int x, int y) {
  return applyAccepted(
    state,
    state.getActor(),
    specialAction(GameActionKind::DOUBLE_START,state.getConfig().getBoardSize(),x,y)
  );
}

CollapseGoApplyResult terminateAccepted(
  CollapseGoState& state,
  Player loser,
  CollapseGoAdministrativeTerminationReason reason
) {
  CollapseGoApplyResult result = CollapseGoReducer::terminate(state,loser,reason);
  if(!result.accepted)
    throw StringError("Expected accepted Collapse Go termination, got " + result.getErrorCode());
  return result;
}

void expectTerminationRejectedAtomically(
  CollapseGoState& state,
  Player loser,
  CollapseGoAdministrativeTerminationReason reason,
  CollapseGoApplyError expectedError
) {
  CollapseGoState before(state);
  CollapseGoApplyResult result = CollapseGoReducer::terminate(state,loser,reason);
  if(result.accepted || result.error != expectedError) {
    CollapseGoApplyResult expected;
    expected.error = expectedError;
    throw StringError(
      "Expected Collapse Go termination rejection " + expected.getErrorCode() +
      ", got " + result.getErrorCode()
    );
  }
  testAssert(result.isSemanticRejection());
  testAssert(!result.isUnsupportedBySlice());
  testAssert(result.capturedStones.empty());
  testAssert(!result.atomicStateSnapshot.has_value());
  testAssert(result.settlementSteps.empty());
  testAssert(!result.settlementTriggered);
  testAssert(result.settlementReason == CollapseGoSettlementReason::NONE);
  testAssert(!result.terminalEvent.has_value());
  testAssert(!result.terminalScoreEventEmitted);
  testAssert(result.positionalSuperkoAppends == 0);
  testAssert(state.isEqualForTesting(before));
}

void expectRejectedAtomically(
  CollapseGoState& state,
  Player actor,
  const GameAction& action,
  CollapseGoApplyError expectedError,
  bool expectedSemanticRejection
) {
  CollapseGoState before(state);
  CollapseGoApplyResult result = CollapseGoReducer::apply(state,actor,action);
  if(result.accepted || result.error != expectedError) {
    CollapseGoApplyResult expected;
    expected.error = expectedError;
    throw StringError(
      "Expected Collapse Go rejection " + expected.getErrorCode() +
      ", got " + result.getErrorCode()
    );
  }
  testAssert(result.isSemanticRejection() == expectedSemanticRejection);
  testAssert(result.isUnsupportedBySlice() == (expectedError == CollapseGoApplyError::UNSUPPORTED_BY_SLICE));
  testAssert(!result.terminalEvent.has_value());
  testAssert(state.isEqualForTesting(before));
}

void expectStringError(const function<void()>& operation) {
  try {
    operation();
  }
  catch(const StringError&) {
    return;
  }
  throw StringError("Expected StringError, but operation succeeded");
}

void playImmortalTrueEyePrefix(CollapseGoState& state) {
  playNormal(state,18,18); playNormal(state,9,8);
  playNormal(state,18,17); playNormal(state,8,9);
  playNormal(state,17,18); playNormal(state,10,9);
  playNormal(state,17,17); playNormal(state,9,10);
  playNormal(state,16,18); playNormal(state,8,8);
  playNormal(state,18,16); playNormal(state,10,8);
  playNormal(state,16,16); playNormal(state,8,10);
  playNormal(state,16,17); playNormal(state,10,10);
}

void playWhiteImmortalTrueEyePrefix(CollapseGoState& state) {
  playNormal(state,9,8); playNormal(state,18,18);
  playNormal(state,8,9); playNormal(state,18,17);
  playNormal(state,10,9); playNormal(state,17,18);
  playNormal(state,9,10); playNormal(state,17,17);
  playNormal(state,8,8); playNormal(state,16,18);
  playNormal(state,10,8); playNormal(state,18,16);
  playNormal(state,8,10); playNormal(state,16,16);
  playNormal(state,10,10); playNormal(state,16,17);
  playPass(state);
}

void playThresholdTrueEyePrefix(CollapseGoState& state) {
  const pair<int,int> blackPoints[] = {
    {0,0},{2,0},{4,0},{6,0},{8,0},{0,8},{2,8},{4,8},{6,8},
    {8,8},{0,2},{0,4},{0,6},{4,3},{3,4},{5,4},{4,5},
  };
  const pair<int,int> whitePoints[] = {
    {1,1},{3,1},{5,1},{7,1},{1,7},{3,7},{5,7},{7,7},
    {2,3},{6,3},{2,5},{6,5},{1,3},{7,3},{1,5},{7,5},
  };
  const size_t blackPointCount = sizeof(blackPoints) / sizeof(blackPoints[0]);
  const size_t whitePointCount = sizeof(whitePoints) / sizeof(whitePoints[0]);
  for(size_t index = 0; index < blackPointCount; index++) {
    playNormal(state,blackPoints[index].first,blackPoints[index].second);
    if(index < whitePointCount)
      playNormal(state,whitePoints[index].first,whitePoints[index].second);
  }
}

struct ImmortalD4Episode {
  vector<GameAction> actions;
  CollapseGoState placementState;
  CollapseGoState finalState;
  CollapseGoApplyResult settlementResult;
};

ImmortalD4Episode runImmortalD4Episode(int symmetry) {
  const int boardSize = 9;
  CollapseGoState state(CollapseGoConfig::allOne(boardSize));
  vector<GameAction> actions;
  auto applyPoint = [&](GameActionKind kind, int x, int y) {
    int transformedPoint = transformPoint(boardSize,y * boardSize + x,symmetry);
    GameAction action = GameAction::fromBoard(
      kind,boardSize,transformedPoint % boardSize,transformedPoint / boardSize
    );
    actions.push_back(action);
    applyAccepted(state,state.getActor(),action);
  };
  auto applyPass = [&]() {
    GameAction action = GameAction::pass();
    actions.push_back(action);
    return applyAccepted(state,state.getActor(),action);
  };

  const pair<int,int> setup[] = {
    {0,0},{4,3},{1,0},{3,4},{2,0},{5,4},{7,7},{4,5},
  };
  for(const pair<int,int>& point: setup)
    applyPoint(GameActionKind::NORMAL,point.first,point.second);
  applyPoint(GameActionKind::IMMORTAL,4,4);
  CollapseGoState placementState(state);
  applyPass();
  CollapseGoApplyResult settlement = applyPass();
  return ImmortalD4Episode{actions,placementState,state,settlement};
}

ImmortalD4Episode runEightwayD4Episode(int symmetry) {
  const int boardSize = 9;
  CollapseGoConfig config(
    boardSize,CollapseGoQuotas(1,0,1),CollapseGoQuotas(0,0,0)
  );
  CollapseGoState state(config);
  vector<GameAction> actions;
  auto applyPoint = [&](GameActionKind kind, int x, int y) {
    int transformedPoint = transformPoint(boardSize,y * boardSize + x,symmetry);
    GameAction action = GameAction::fromBoard(
      kind,boardSize,transformedPoint % boardSize,transformedPoint / boardSize
    );
    actions.push_back(action);
    applyAccepted(state,state.getActor(),action);
  };
  auto applyPass = [&]() {
    GameAction action = GameAction::pass();
    actions.push_back(action);
    return applyAccepted(state,state.getActor(),action);
  };

  applyPoint(GameActionKind::IMMORTAL,1,1);
  applyPoint(GameActionKind::NORMAL,2,1);
  applyPoint(GameActionKind::NORMAL,3,1);
  applyPoint(GameActionKind::NORMAL,1,2);
  applyPoint(GameActionKind::NORMAL,8,8);
  applyPoint(GameActionKind::NORMAL,3,2);
  applyPoint(GameActionKind::NORMAL,8,7);
  applyPoint(GameActionKind::NORMAL,2,3);
  applyPoint(GameActionKind::EIGHTWAY,2,2);
  applyPoint(GameActionKind::NORMAL,3,0);
  applyPoint(GameActionKind::NORMAL,7,8);
  applyPoint(GameActionKind::NORMAL,4,1);
  CollapseGoState placementState(state);
  applyPass();
  CollapseGoApplyResult settlement = applyPass();
  return ImmortalD4Episode{actions,placementState,state,settlement};
}

ImmortalD4Episode runCapturedEightwayD4Episode(int symmetry) {
  const int boardSize = 9;
  CollapseGoConfig config(
    boardSize,CollapseGoQuotas(0,0,1),CollapseGoQuotas(0,0,0)
  );
  CollapseGoState state(config);
  vector<GameAction> actions;
  auto applyPoint = [&](GameActionKind kind, int x, int y) {
    int transformedPoint = transformPoint(boardSize,y * boardSize + x,symmetry);
    GameAction action = GameAction::fromBoard(
      kind,boardSize,transformedPoint % boardSize,transformedPoint / boardSize
    );
    actions.push_back(action);
    return applyAccepted(state,state.getActor(),action);
  };
  auto applyPass = [&]() {
    GameAction action = GameAction::pass();
    actions.push_back(action);
    return applyAccepted(state,state.getActor(),action);
  };

  applyPoint(GameActionKind::EIGHTWAY,4,4);
  const pair<int,int> ring[8] = {
    {3,3},{4,3},{5,3},{3,4},{5,4},{3,5},{4,5},{5,5},
  };
  for(int index = 0; index < 8; index++) {
    applyPoint(GameActionKind::NORMAL,ring[index].first,ring[index].second);
    if(index < 7)
      applyPoint(GameActionKind::NORMAL,index,8);
  }
  CollapseGoState placementState(state);
  applyPass();
  CollapseGoApplyResult settlement = applyPass();
  return ImmortalD4Episode{actions,placementState,state,settlement};
}

struct AdministrativeD4Episode {
  vector<GameAction> actions;
  CollapseGoState pendingState;
  CollapseGoState terminalState;
  CollapseGoApplyResult terminationResult;
};

AdministrativeD4Episode runAdministrativeD4Episode(int symmetry) {
  const int boardSize = 9;
  CollapseGoState state(CollapseGoConfig::allOne(boardSize));
  const int transformedPoint = transformPoint(boardSize,2 + 3 * boardSize,symmetry);
  GameAction start = GameAction::fromBoard(
    GameActionKind::DOUBLE_START,
    boardSize,
    transformedPoint % boardSize,
    transformedPoint / boardSize
  );
  applyAccepted(state,state.getActor(),start);
  CollapseGoState pendingState(state);
  CollapseGoApplyResult termination = terminateAccepted(
    state,P_WHITE,CollapseGoAdministrativeTerminationReason::TIMEOUT
  );
  return AdministrativeD4Episode{{start},pendingState,state,termination};
}

void assertD4Actions(
  const vector<GameAction>& reference,
  const vector<GameAction>& transformed,
  int boardSize,
  int symmetry
) {
  testAssert(reference.size() == transformed.size());
  for(size_t index = 0; index < reference.size(); index++) {
    testAssert(reference[index].getKind() == transformed[index].getKind());
    if(!GameAction::isPointKind(reference[index].getKind()))
      continue;
    int referencePoint = reference[index].getBoardY(boardSize) * boardSize +
      reference[index].getBoardX(boardSize);
    int transformedPoint = transformed[index].getBoardY(boardSize) * boardSize +
      transformed[index].getBoardX(boardSize);
    testAssert(transformedPoint == transformPoint(boardSize,referencePoint,symmetry));
  }
}

void assertD4State(
  const CollapseGoState& reference,
  const CollapseGoState& transformed,
  int symmetry
) {
  const int boardSize = reference.getConfig().getBoardSize();
  testAssert(transformed.getConfig() == reference.getConfig());
  testAssert(transformed.getPhase() == reference.getPhase());
  testAssert(transformed.getActor() == reference.getActor());
  testAssert(transformed.getAtomicActionCount() == reference.getAtomicActionCount());
  testAssert(transformed.getConsecutivePasses() == reference.getConsecutivePasses());
  testAssert(transformed.isSettlementCompleted() == reference.isSettlementCompleted());
  testAssert(transformed.getRevision() == reference.getRevision());
  testAssert(transformed.getLogPosition() == reference.getLogPosition());
  testAssert(transformed.getSettledLedgerCount() == reference.getSettledLedgerCount());
  testAssert(transformed.getStableTerminalEventCount() == reference.getStableTerminalEventCount());
  testAssert(transformed.getPendingDouble() == reference.getPendingDouble());
  testAssert(transformed.getTerminalState() == reference.getTerminalState());
  testAssert(transformed.getScore() == reference.getScore());

  for(Player player: {P_BLACK,P_WHITE}) {
    for(CollapseGoAbility ability: {
      CollapseGoAbility::IMMORTAL,
      CollapseGoAbility::DOUBLE_MOVE,
      CollapseGoAbility::EIGHTWAY,
    }) {
      testAssert(transformed.getInitialQuota(player,ability) == reference.getInitialQuota(player,ability));
      testAssert(transformed.getRemainingQuota(player,ability) == reference.getRemainingQuota(player,ability));
      testAssert(transformed.getUsedQuota(player,ability) == reference.getUsedQuota(player,ability));
      testAssert(transformed.getExpiredQuota(player,ability) == reference.getExpiredQuota(player,ability));
    }
  }

  for(int point = 0; point < reference.getPosition().getPointCount(); point++) {
    int transformedPoint = transformPoint(boardSize,point,symmetry);
    const CollapseGoCell& referenceCell = reference.getPosition().getCell(point);
    const CollapseGoCell& transformedCell = transformed.getPosition().getCell(transformedPoint);
    testAssert(transformedCell.getColor() == referenceCell.getColor());
    if(referenceCell.isOccupied())
      testAssert(transformedCell.getSource() == referenceCell.getSource());
  }

  const CollapseGoLedger& referenceLedger = reference.getLedger();
  const CollapseGoLedger& transformedLedger = transformed.getLedger();
  testAssert(transformedLedger.size() == referenceLedger.size());
  for(size_t index = 0; index < referenceLedger.size(); index++) {
    const CollapseGoLedgerEntry& referenceEntry = referenceLedger.at(index);
    const CollapseGoLedgerEntry& transformedEntry = transformedLedger.at(index);
    testAssert(transformedEntry.specialLink == referenceEntry.specialLink);
    testAssert(transformedEntry.originActionNumber == referenceEntry.originActionNumber);
    testAssert(transformedEntry.owner == referenceEntry.owner);
    testAssert(transformedEntry.originKind == referenceEntry.originKind);
    testAssert(transformedEntry.sourcePoint == transformPoint(
      boardSize,referenceEntry.sourcePoint,symmetry
    ));
    testAssert(transformedEntry.abilityState == referenceEntry.abilityState);
    testAssert(transformedEntry.stoneState == referenceEntry.stoneState);
    testAssert(transformedEntry.settlementState == referenceEntry.settlementState);
    testAssert(transformedEntry.tombstone == referenceEntry.tombstone);
  }

  vector<int> expectedAnchors;
  for(int point: reference.getArmedImmortalAnchors())
    expectedAnchors.push_back(transformPoint(boardSize,point,symmetry));
  sort(expectedAnchors.begin(),expectedAnchors.end());
  testAssert(transformed.getArmedImmortalAnchors() == expectedAnchors);

  vector<int> expectedEightwaySources;
  for(int point: reference.getArmedEightwaySources())
    expectedEightwaySources.push_back(transformPoint(boardSize,point,symmetry));
  sort(expectedEightwaySources.begin(),expectedEightwaySources.end());
  testAssert(transformed.getArmedEightwaySources() == expectedEightwaySources);

  const PositionalSuperkoHistory& referenceHistory = reference.getPositionalSuperkoHistory();
  const PositionalSuperkoHistory& transformedHistory = transformed.getPositionalSuperkoHistory();
  testAssert(transformedHistory.size() == referenceHistory.size());
  for(size_t index = 0; index < referenceHistory.size(); index++) {
    testAssert(transformedHistory.at(index).getOccupancy() == transformedOccupancy(
      referenceHistory.at(index).getOccupancy(),boardSize,symmetry
    ));
  }

  CollapseGoTopology referenceTopology = CollapseGoTopology::fullScan(
    reference.getPosition(),
    reference.getArmedImmortalAnchors(),
    reference.getArmedEightwaySources()
  );
  CollapseGoTopology transformedTopology = CollapseGoTopology::fullScan(
    transformed.getPosition(),
    transformed.getArmedImmortalAnchors(),
    transformed.getArmedEightwaySources()
  );
  testAssert(transformedTopology.getGroups() == transformedGroups(
    referenceTopology.getGroups(),boardSize,symmetry
  ));
}

void assertD4Settlement(
  const CollapseGoApplyResult& reference,
  const CollapseGoApplyResult& transformed,
  int boardSize,
  int symmetry
) {
  testAssert(transformed.accepted == reference.accepted);
  testAssert(transformed.error == reference.error);
  testAssert(transformed.capturedStones == transformedLocs(
    reference.capturedStones,boardSize,symmetry
  ));
  testAssert(transformed.settlementTriggered == reference.settlementTriggered);
  testAssert(transformed.settlementReason == reference.settlementReason);
  testAssert(transformed.terminalEvent.has_value() == reference.terminalEvent.has_value());
  if(reference.terminalEvent.has_value()) {
    const CollapseGoTerminalEvent& referenceEvent = *reference.terminalEvent;
    const CollapseGoTerminalEvent& transformedEvent = *transformed.terminalEvent;
    testAssert(transformedEvent.reason == referenceEvent.reason);
    testAssert(transformedEvent.winner == referenceEvent.winner);
    testAssert(transformedEvent.loser == referenceEvent.loser);
    testAssert(transformedEvent.score == referenceEvent.score);
    testAssert(transformedEvent.settlementCompleted == referenceEvent.settlementCompleted);
    assertTransformedPosition(
      referenceEvent.stablePosition,transformedEvent.stablePosition,boardSize,symmetry
    );
    testAssert(transformedEvent.stableOccupancy == transformedOccupancy(
      referenceEvent.stableOccupancy,boardSize,symmetry
    ));
    testAssert(transformedEvent.positionalSuperkoHistoryIndex ==
      referenceEvent.positionalSuperkoHistoryIndex);
    testAssert(transformedEvent.revision == referenceEvent.revision);
    testAssert(transformedEvent.logPosition == referenceEvent.logPosition);
  }
  testAssert(transformed.terminalScoreEventEmitted == reference.terminalScoreEventEmitted);
  testAssert(transformed.positionalSuperkoAppends == reference.positionalSuperkoAppends);
  testAssert(transformed.settlementSteps.size() == reference.settlementSteps.size());
  for(size_t index = 0; index < reference.settlementSteps.size(); index++) {
    const CollapseGoSettlementStep& referenceStep = reference.settlementSteps[index];
    const CollapseGoSettlementStep& transformedStep = transformed.settlementSteps[index];
    testAssert(transformedStep.stepIndex == referenceStep.stepIndex);
    testAssert(transformedStep.specialLink == referenceStep.specialLink);
    testAssert(transformedStep.originActionNumber == referenceStep.originActionNumber);
    testAssert(transformedStep.owner == referenceStep.owner);
    testAssert(transformedStep.originKind == referenceStep.originKind);
    testAssert(transformedStep.sourcePoint == transformPoint(
      boardSize,referenceStep.sourcePoint,symmetry
    ));
    testAssert(transformedStep.noOp == referenceStep.noOp);
    testAssert(transformedStep.abilityDeactivated == referenceStep.abilityDeactivated);
    testAssert(transformedStep.removalBatches.size() == referenceStep.removalBatches.size());
    for(size_t batchIndex = 0; batchIndex < referenceStep.removalBatches.size(); batchIndex++) {
      const CollapseGoRemovalBatch& referenceBatch = referenceStep.removalBatches[batchIndex];
      const CollapseGoRemovalBatch& transformedBatch = transformedStep.removalBatches[batchIndex];
      testAssert(transformedBatch.blackStones == transformedLocs(
        referenceBatch.blackStones,boardSize,symmetry
      ));
      testAssert(transformedBatch.whiteStones == transformedLocs(
        referenceBatch.whiteStones,boardSize,symmetry
      ));
    }
    testAssert(transformedStep.stableOccupancy == transformedOccupancy(
      referenceStep.stableOccupancy,boardSize,symmetry
    ));
    testAssert(transformedStep.positionalSuperkoHistoryIndex ==
      referenceStep.positionalSuperkoHistoryIndex);
  }
}

void playProtectedAttachmentPrefix(CollapseGoState& state) {
  playNormal(state,8,8); playNormal(state,1,2);
  playNormal(state,8,7); playNormal(state,3,2);
  playNormal(state,7,8); playNormal(state,2,1);
  playNormal(state,7,7); playNormal(state,1,3);
  playNormal(state,6,8); playNormal(state,3,3);
  playNormal(state,6,7); playNormal(state,2,4);
  playImmortal(state,2,2);
  playNormal(state,0,0);
}

void enterOrdinaryPlay(CollapseGoState& state) {
  CollapseGoApplyResult firstPass = playPass(state);
  testAssert(!firstPass.settlementTriggered);
  CollapseGoApplyResult secondPass = playPass(state);
  testAssert(secondPass.settlementTriggered);
  testAssert(secondPass.settlementReason == CollapseGoSettlementReason::PRE_THRESHOLD_TWO_PASSES);
  testAssert(state.getPhase() == CollapseGoPhase::ORDINARY_PLAY);
}

void assertNonDecisionSnapshotFailsClosed(const CollapseGoState& snapshot) {
  CollapseGoState before(snapshot);
  CollapseGoLegalMask first = CollapseGoReducer::deriveLegalMask(snapshot);
  CollapseGoLegalMask second = CollapseGoReducer::deriveLegalMask(snapshot);
  testAssert(first.none());
  testAssert(second.none());
  testAssert(snapshot.isEqualForTesting(before));

  CollapseGoState candidate(snapshot);
  CollapseGoApplyResult rejected = CollapseGoReducer::apply(
    candidate,
    getOpp(snapshot.getActor()),
    GameAction::fromCanvas(GameActionKind::IMMORTAL,0,0)
  );
  testAssert(!rejected.accepted);
  testAssert(rejected.error == CollapseGoApplyError::INTERNAL_INVARIANT);
  testAssert(rejected.capturedStones.empty());
  testAssert(!rejected.atomicStateSnapshot.has_value());
  testAssert(rejected.settlementSteps.empty());
  testAssert(!rejected.settlementTriggered);
  testAssert(rejected.settlementReason == CollapseGoSettlementReason::NONE);
  testAssert(!rejected.terminalEvent.has_value());
  testAssert(!rejected.terminalScoreEventEmitted);
  testAssert(rejected.positionalSuperkoAppends == 0);
  testAssert(candidate.isEqualForTesting(before));
  testAssert(snapshot.isEqualForTesting(before));

  CollapseGoState terminationCandidate(snapshot);
  expectTerminationRejectedAtomically(
    terminationCandidate,
    P_BLACK,
    CollapseGoAdministrativeTerminationReason::RESIGNATION,
    CollapseGoApplyError::INTERNAL_INVARIANT
  );
  testAssert(snapshot.isEqualForTesting(before));
}

CollapseGoLegalMask assertLegalMaskMatchesApply(const CollapseGoState& state) {
  state.checkConsistency();
  CollapseGoState before(state);
  CollapseGoLegalMask first = CollapseGoReducer::deriveLegalMask(state);
  CollapseGoLegalMask second = CollapseGoReducer::deriveLegalMask(state);
  if(first != second)
    throw StringError("Collapse Go legal-mask derivation is nondeterministic");
  if(!state.isEqualForTesting(before))
    throw StringError("Collapse Go legal-mask derivation mutated its source state");
  testAssert(first.size() == static_cast<size_t>(GameAction::FLAT_ACTION_COUNT));

  for(int actionId = 0; actionId < GameAction::FLAT_ACTION_COUNT; actionId++) {
    CollapseGoState candidate(state);
    CollapseGoApplyResult result = CollapseGoReducer::apply(
      candidate,state.getActor(),GameAction::decode(actionId)
    );
    if(first.test(static_cast<size_t>(actionId)) != result.accepted)
      throw StringError("Collapse Go legal-mask mismatch at action " + to_string(actionId));
    if(!result.accepted && !candidate.isEqualForTesting(state))
      throw StringError("Rejected Collapse Go mask oracle action mutated its fresh state copy");
  }

  if(!state.isEqualForTesting(before))
    throw StringError("Collapse Go legal-mask equivalence checks mutated their source state");
  if(state.getPhase() == CollapseGoPhase::TERMINAL)
    testAssert(first.none());
  else
    testAssert(first.test(static_cast<size_t>(GameAction::PASS_ACTION_ID)));
  return first;
}

using CollapseGoReplayStep = pair<Player,GameAction>;

struct CollapseGoSuffixRecord {
  vector<CollapseGoLegalMask> legalMasks;
  vector<CollapseGoApplyResult> results;
  vector<CollapseGoState> statesAfterActions;
  CollapseGoState finalState;
};

CollapseGoLegalMask deriveStableReplayMask(const CollapseGoState& state) {
  CollapseGoState before(state);
  CollapseGoLegalMask first = CollapseGoReducer::deriveLegalMask(state);
  CollapseGoLegalMask second = CollapseGoReducer::deriveLegalMask(state);
  testAssert(first == second);
  testAssert(state.isEqualForTesting(before));
  return first;
}

CollapseGoSuffixRecord recordAcceptedSuffix(
  CollapseGoState& state,
  const vector<CollapseGoReplayStep>& suffix
) {
  vector<CollapseGoLegalMask> legalMasks;
  vector<CollapseGoApplyResult> results;
  vector<CollapseGoState> statesAfterActions;
  legalMasks.reserve(suffix.size() + 1);
  results.reserve(suffix.size());
  statesAfterActions.reserve(suffix.size());

  for(size_t index = 0; index < suffix.size(); index++) {
    legalMasks.push_back(deriveStableReplayMask(state));
    CollapseGoApplyResult result = CollapseGoReducer::apply(
      state,suffix[index].first,suffix[index].second
    );
    if(!result.accepted)
      throw StringError(
        "Expected accepted Collapse Go replay suffix action " + to_string(index) +
        ", got " + result.getErrorCode()
      );
    state.checkConsistency();
    results.push_back(result);
    statesAfterActions.push_back(state);
  }
  legalMasks.push_back(deriveStableReplayMask(state));
  return CollapseGoSuffixRecord{legalMasks,results,statesAfterActions,state};
}

bool applyResultsEqualForTesting(
  const CollapseGoApplyResult& expected,
  const CollapseGoApplyResult& actual
) {
  if(actual.accepted != expected.accepted || actual.error != expected.error ||
     actual.capturedStones != expected.capturedStones ||
     actual.atomicStateSnapshot.has_value() != expected.atomicStateSnapshot.has_value())
    return false;
  if(expected.atomicStateSnapshot.has_value() &&
     !actual.atomicStateSnapshot->isEqualForTesting(*expected.atomicStateSnapshot))
    return false;
  return actual.settlementSteps == expected.settlementSteps &&
    actual.settlementTriggered == expected.settlementTriggered &&
    actual.settlementReason == expected.settlementReason &&
    actual.terminalEvent == expected.terminalEvent &&
    actual.terminalScoreEventEmitted == expected.terminalScoreEventEmitted &&
    actual.positionalSuperkoAppends == expected.positionalSuperkoAppends;
}

void assertExactApplyResult(
  const CollapseGoApplyResult& expected,
  const CollapseGoApplyResult& actual
) {
  testAssert(applyResultsEqualForTesting(expected,actual));
}

void assertExactSuffixRecord(
  const CollapseGoSuffixRecord& expected,
  const CollapseGoSuffixRecord& actual
) {
  testAssert(actual.legalMasks == expected.legalMasks);
  testAssert(actual.results.size() == expected.results.size());
  for(size_t index = 0; index < expected.results.size(); index++)
    assertExactApplyResult(expected.results[index],actual.results[index]);
  testAssert(actual.statesAfterActions.size() == expected.statesAfterActions.size());
  for(size_t index = 0; index < expected.statesAfterActions.size(); index++)
    testAssert(actual.statesAfterActions[index].isEqualForTesting(expected.statesAfterActions[index]));
  testAssert(actual.finalState.isEqualForTesting(expected.finalState));
}

CollapseGoSuffixRecord assertDeterministicSuffixReplay(
  CollapseGoState checkpoint,
  const vector<CollapseGoReplayStep>& prefix,
  const vector<CollapseGoReplayStep>& suffix
) {
  checkpoint.checkConsistency();
  CollapseGoState immutableCheckpoint(checkpoint);
  CollapseGoLegalMask checkpointMask = deriveStableReplayMask(checkpoint);

  CollapseGoState working(checkpoint);
  CollapseGoSuffixRecord first = recordAcceptedSuffix(working,suffix);
  testAssert(checkpoint.isEqualForTesting(immutableCheckpoint));
  testAssert(deriveStableReplayMask(checkpoint) == checkpointMask);

  working = checkpoint;
  testAssert(working.isEqualForTesting(checkpoint));
  testAssert(deriveStableReplayMask(working) == checkpointMask);
  CollapseGoSuffixRecord restored = recordAcceptedSuffix(working,suffix);
  assertExactSuffixRecord(first,restored);

  CollapseGoState fresh(checkpoint.getConfig());
  for(const CollapseGoReplayStep& step: prefix)
    applyAccepted(fresh,step.first,step.second);
  fresh.checkConsistency();
  testAssert(fresh.isEqualForTesting(checkpoint));
  testAssert(deriveStableReplayMask(fresh) == checkpointMask);
  CollapseGoSuffixRecord freshReplay = recordAcceptedSuffix(fresh,suffix);
  assertExactSuffixRecord(first,freshReplay);

  testAssert(checkpoint.isEqualForTesting(immutableCheckpoint));
  testAssert(deriveStableReplayMask(checkpoint) == checkpointMask);
  return first;
}

void assertD4LegalMask(
  const CollapseGoLegalMask& reference,
  const CollapseGoLegalMask& transformed,
  int symmetry
) {
  for(int actionId = 0; actionId < GameAction::FLAT_ACTION_COUNT; actionId++) {
    int transformedActionId = GameAction::decode(actionId).transformed(symmetry).getActionId();
    if(reference.test(static_cast<size_t>(actionId)) !=
       transformed.test(static_cast<size_t>(transformedActionId)))
      throw StringError("Collapse Go D4 legal-mask mismatch at action " + to_string(actionId));
  }
}

void playToAtomicActionCount(CollapseGoState& state, int64_t targetCount) {
  int nextPoint = 0;
  while(state.getAtomicActionCount() < targetCount) {
    if(targetCount - state.getAtomicActionCount() >= 2)
      playPass(state);
    while(nextPoint < state.getPosition().getPointCount() &&
          !state.getPosition().isEmpty(nextPoint))
      nextPoint++;
    if(nextPoint >= state.getPosition().getPointCount())
      throw StringError("Collapse Go threshold-mask setup ran out of empty points");
    playNormal(
      state,
      state.getPosition().getX(nextPoint),
      state.getPosition().getY(nextPoint)
    );
    nextPoint++;
  }
  testAssert(state.getAtomicActionCount() == targetCount);
  testAssert(state.getPhase() == CollapseGoPhase::COLLAPSE_PLAY);
}

int actionIdAt(GameActionKind kind, int boardSize, int x, int y) {
  return GameAction::fromBoard(kind,boardSize,x,y).getActionId();
}

}

void Tests::runCollapseReducerTests() {
  cout << "Running Collapse Go reducer slice tests" << endl;

  // Configuration, thresholds, and exact initial PSK seeding.
  {
    testAssert(CollapseGoConfig::thresholdForBoardSize(9) == 34);
    testAssert(CollapseGoConfig::thresholdForBoardSize(13) == 70);
    testAssert(CollapseGoConfig::thresholdForBoardSize(19) == 150);
    expectStringError([]() { CollapseGoConfig::allZero(11); });
    CollapseGoLedgerEntry eightwayEntry(1,1,P_BLACK,GameActionKind::EIGHTWAY,0);
    testAssert(eightwayEntry.abilityState == CollapseGoLedgerAbilityState::ARMED);
    testAssert(eightwayEntry.stoneState == CollapseGoLedgerStoneState::ON_BOARD);
    testAssert(eightwayEntry.settlementState == CollapseGoLedgerSettlementState::PENDING);
    testAssert(!eightwayEntry.tombstone);
    expectStringError([]() {
      CollapseGoConfig(9,CollapseGoQuotas(-1,0,0),CollapseGoQuotas());
    });

    static constexpr int64_t safeIntegerMaximum = 9007199254740991LL;
    CollapseGoConfig safeMaximum(
      9,
      CollapseGoQuotas(safeIntegerMaximum,0,0),
      CollapseGoQuotas(0,safeIntegerMaximum,safeIntegerMaximum)
    );
    testAssert(safeMaximum.getInitialQuota(P_BLACK,CollapseGoAbility::IMMORTAL) == safeIntegerMaximum);
    testAssert(safeMaximum.getInitialQuota(P_WHITE,CollapseGoAbility::DOUBLE_MOVE) == safeIntegerMaximum);
    testAssert(safeMaximum.getInitialQuota(P_WHITE,CollapseGoAbility::EIGHTWAY) == safeIntegerMaximum);
    CollapseGoState safeMaximumState(safeMaximum);
    testAssert(safeMaximumState.getRemainingQuota(P_BLACK,CollapseGoAbility::IMMORTAL) == safeIntegerMaximum);
    testAssert(safeMaximumState.getRemainingQuota(P_WHITE,CollapseGoAbility::DOUBLE_MOVE) == safeIntegerMaximum);
    safeMaximumState.checkConsistency();
    expectStringError([]() {
      CollapseGoConfig(9,CollapseGoQuotas(9007199254740992LL,0,0),CollapseGoQuotas());
    });
    expectStringError([]() {
      CollapseGoConfig(9,CollapseGoQuotas(),CollapseGoQuotas(0,numeric_limits<int64_t>::max(),0));
    });

    CollapseGoConfig mixed(13,CollapseGoQuotas(2,0,3),CollapseGoQuotas(0,4,0));
    testAssert(mixed.getInitialQuota(P_BLACK,CollapseGoAbility::IMMORTAL) == 2);
    testAssert(mixed.getInitialQuota(P_BLACK,CollapseGoAbility::DOUBLE_MOVE) == 0);
    testAssert(mixed.getInitialQuota(P_BLACK,CollapseGoAbility::EIGHTWAY) == 3);
    testAssert(mixed.getInitialQuota(P_WHITE,CollapseGoAbility::DOUBLE_MOVE) == 4);
    testAssert(mixed.getInitialQuota(P_WHITE,CollapseGoAbility::EIGHTWAY) == 0);

    CollapseGoState state(CollapseGoConfig::allOne(9));
    state.checkConsistency();
    const PositionalSuperkoHistory& history = state.getPositionalSuperkoHistory();
    testAssert(history.size() == 1);
    const CollapseGoPosition& position = state.getPosition();
    testAssert(history.at(0) == PositionalSuperkoKey(position.getBoardSize(),position.getRowMajorOccupancy()));
    testAssert(history.at(0).getOccupancy().size() == 81);
    for(uint8_t color: history.at(0).getOccupancy())
      testAssert(color == C_EMPTY);
    testAssert(state.getLedger().empty());
    testAssert(!state.getPendingDouble().has_value());
    testAssert(state.getRevision() == 0);
    testAssert(state.getLogPosition() == 0);
    testAssert(state.getSettledLedgerCount() == 0);
    testAssert(state.getStableTerminalEventCount() == 0);
    testAssert(!state.getTerminalState().has_value());
    testAssert(state.getScore() == CollapseGoScore());

    CollapseGoTerminalState scoreTerminal(
      CollapseGoTerminalReason::SCORE,P_BLACK,P_WHITE
    );
    testAssert(scoreTerminal == CollapseGoTerminalState(
      CollapseGoTerminalReason::SCORE,P_BLACK,P_WHITE
    ));
    testAssert(scoreTerminal != CollapseGoTerminalState(
      CollapseGoTerminalReason::SCORE,P_WHITE,P_BLACK
    ));
    expectStringError([]() {
      CollapseGoTerminalState(
        static_cast<CollapseGoTerminalReason>(-1),P_BLACK,P_WHITE
      );
    });
    expectStringError([]() {
      CollapseGoTerminalState(CollapseGoTerminalReason::TIMEOUT,C_EMPTY,P_BLACK);
    });
    expectStringError([]() {
      CollapseGoTerminalState(CollapseGoTerminalReason::RESIGNATION,P_BLACK,P_BLACK);
    });

    static_assert(!is_constructible<
      CollapseGoTerminalEvent,
      const CollapseGoTerminalState&,
      const CollapseGoScore&,
      const vector<uint8_t>&,
      int64_t,
      int64_t,
      int64_t
    >::value,"Collapse Go terminal events must not accept arbitrary payloads");
    static_assert(!is_constructible<
      CollapseGoTerminalEvent,
      const CollapseGoState&
    >::value,"Collapse Go terminal-event state construction must remain factory-only");

    CollapseGoState nonterminal(CollapseGoConfig::allOne(9));
    expectStringError([&]() {
      (void)CollapseGoTerminalEvent::fromCommittedState(nonterminal);
    });

    for(int boardSize: {9,13,19}) {
      CollapseGoState administrativeState(CollapseGoConfig::allOne(boardSize));
      CollapseGoApplyResult administrativeResult = terminateAccepted(
        administrativeState,P_BLACK,CollapseGoAdministrativeTerminationReason::RESIGNATION
      );
      testAssert(administrativeResult.terminalEvent.has_value());
      const CollapseGoTerminalEvent& administrativeEvent = *administrativeResult.terminalEvent;
      administrativeEvent.validateAgainstCommittedState(administrativeState);
      testAssert(administrativeEvent.reason == CollapseGoTerminalReason::RESIGNATION);
      testAssert(administrativeEvent.score == CollapseGoScore());
      testAssert(administrativeEvent.stableOccupancy.size() ==
        static_cast<size_t>(boardSize * boardSize));

      CollapseGoState scoredState(CollapseGoConfig::allOne(boardSize));
      enterOrdinaryPlay(scoredState);
      playPass(scoredState);
      CollapseGoApplyResult scoreResult = playPass(scoredState);
      testAssert(scoreResult.terminalScoreEventEmitted);
      testAssert(scoreResult.terminalEvent.has_value());
      const CollapseGoTerminalEvent& scoreEvent = *scoreResult.terminalEvent;
      scoreEvent.validateAgainstCommittedState(scoredState);
      testAssert(scoreEvent.reason == CollapseGoTerminalReason::SCORE);
      testAssert(scoreEvent.score == scoredState.getScore());
      testAssert(scoreEvent.stableOccupancy.size() == static_cast<size_t>(boardSize * boardSize));
    }

    Board metadataOnlyDifference(9,9);
    metadataOnlyDifference.setSimpleKoLoc(Location::getLoc(4,4,9));
    metadataOnlyDifference.numBlackCaptures = 7;
    metadataOnlyDifference.numWhiteCaptures = 11;
    testAssert(PositionalSuperkoKey(metadataOnlyDifference) == history.at(0));
    testAssert(PositionalSuperkoKey(9,position.getRowMajorOccupancy()) == PositionalSuperkoKey(metadataOnlyDifference));

    PositionalSuperkoHistory dimensionCheckedHistory(history.at(0));
    vector<uint8_t> empty13(13 * 13,static_cast<uint8_t>(C_EMPTY));
    expectStringError([&]() { dimensionCheckedHistory.append(PositionalSuperkoKey(13,empty13)); });
    Board board13(13,13);
    expectStringError([&]() { dimensionCheckedHistory.append(board13); });
  }

  // Restored or fabricated shells must retain exact PSK seeding, Double timing, history evidence, and pending control.
  {
    CollapseGoState invalidInitialPsk(CollapseGoConfig::allZero(9));
    playNormal(invalidInitialPsk,4,4);
    CollapseGoStateTestAccess::replacePskOccupancy(
      invalidInitialPsk,
      0,
      invalidInitialPsk.getPositionalSuperkoHistory().at(1).getOccupancy()
    );
    expectStringError([&]() { invalidInitialPsk.checkConsistency(); });

    CollapseGoState missingPending(CollapseGoConfig::allOne(9));
    playDoubleStart(missingPending,4,4);
    CollapseGoStateTestAccess::clearPendingDouble(missingPending);
    expectStringError([&]() { missingPending.checkConsistency(); });

    CollapseGoState mismatchedPending(CollapseGoConfig::allOne(9));
    playDoubleStart(mismatchedPending,4,4);
    CollapseGoStateTestAccess::setPendingDouble(mismatchedPending,P_BLACK,2,1);
    expectStringError([&]() { mismatchedPending.checkConsistency(); });

    CollapseGoState capturedPendingSource(CollapseGoConfig::allOne(9));
    playDoubleStart(capturedPendingSource,4,4);
    CollapseGoStateTestAccess::ledgerEntry(capturedPendingSource,0).stoneState =
      CollapseGoLedgerStoneState::CAPTURED;
    expectStringError([&]() { capturedPendingSource.checkConsistency(); });

    CollapseGoState spuriousPending(CollapseGoConfig::allOne(9));
    playDoubleStart(spuriousPending,4,4);
    playPass(spuriousPending);
    CollapseGoStateTestAccess::setPendingDouble(spuriousPending,P_WHITE,1,2);
    expectStringError([&]() { spuriousPending.checkConsistency(); });

    auto makeCapturedDoubleState = []() {
      CollapseGoState state(CollapseGoConfig::allOne(9));
      playDoubleStart(state,1,1);
      playNormal(state,8,8);
      playNormal(state,1,0); playNormal(state,8,7);
      playNormal(state,0,1); playNormal(state,7,8);
      playNormal(state,2,1); playNormal(state,7,7);
      playNormal(state,1,2);
      testAssert(state.getLedger().at(0).stoneState == CollapseGoLedgerStoneState::CAPTURED);
      state.checkConsistency();
      return state;
    };

    CollapseGoState missingStartHistory = makeCapturedDoubleState();
    playPass(missingStartHistory);
    playPass(missingStartHistory);
    vector<uint8_t> alteredStartOccupancy =
      missingStartHistory.getPositionalSuperkoHistory().at(1).getOccupancy();
    alteredStartOccupancy[static_cast<size_t>(1 + 1 * 9)] = static_cast<uint8_t>(C_EMPTY);
    CollapseGoStateTestAccess::replacePskOccupancy(missingStartHistory,1,alteredStartOccupancy);
    expectStringError([&]() { missingStartHistory.checkConsistency(); });

    CollapseGoState forgedSourcePoint(CollapseGoConfig::allOne(9));
    playNormal(forgedSourcePoint,4,4); playNormal(forgedSourcePoint,8,8);
    playDoubleStart(forgedSourcePoint,1,1);
    playNormal(forgedSourcePoint,7,8);
    playNormal(forgedSourcePoint,1,0); playNormal(forgedSourcePoint,7,7);
    playNormal(forgedSourcePoint,0,1); playNormal(forgedSourcePoint,6,8);
    playNormal(forgedSourcePoint,2,1); playNormal(forgedSourcePoint,6,7);
    playNormal(forgedSourcePoint,1,2);
    testAssert(forgedSourcePoint.getLedger().at(0).stoneState == CollapseGoLedgerStoneState::CAPTURED);
    playPass(forgedSourcePoint);
    playPass(forgedSourcePoint);
    CollapseGoStateTestAccess::ledgerEntry(forgedSourcePoint,0).sourcePoint = 4 + 4 * 9;
    expectStringError([&]() { forgedSourcePoint.checkConsistency(); });

    CollapseGoState invalidThresholdOrigin = makeCapturedDoubleState();
    for(int i = 0; i < 12; i++) {
      playPass(invalidThresholdOrigin);
      playNormal(invalidThresholdOrigin,i % 6,4 + i / 6);
    }
    testAssert(invalidThresholdOrigin.getAtomicActionCount() == 33);
    CollapseGoApplyResult threshold = playNormal(invalidThresholdOrigin,4,8);
    testAssert(threshold.settlementTriggered);
    testAssert(invalidThresholdOrigin.getAtomicActionCount() == 34);
    CollapseGoLedgerEntry& thresholdEntry = CollapseGoStateTestAccess::ledgerEntry(invalidThresholdOrigin,0);
    thresholdEntry.originActionNumber = 34;
    thresholdEntry.specialLink = 34;
    expectStringError([&]() { invalidThresholdOrigin.checkConsistency(); });

    CollapseGoState adjacentOrigins(CollapseGoConfig::allOne(9));
    playDoubleStart(adjacentOrigins,8,8);
    playNormal(adjacentOrigins,7,8);
    playDoubleStart(adjacentOrigins,1,1);
    playNormal(adjacentOrigins,8,7);
    playNormal(adjacentOrigins,1,0); playNormal(adjacentOrigins,7,7);
    playNormal(adjacentOrigins,0,1); playNormal(adjacentOrigins,6,7);
    playNormal(adjacentOrigins,2,1); playNormal(adjacentOrigins,6,6);
    playNormal(adjacentOrigins,1,2);
    testAssert(adjacentOrigins.getLedger().at(1).stoneState == CollapseGoLedgerStoneState::CAPTURED);
    playPass(adjacentOrigins);
    playPass(adjacentOrigins);
    CollapseGoLedgerEntry& adjacentEntry = CollapseGoStateTestAccess::ledgerEntry(adjacentOrigins,1);
    adjacentEntry.originActionNumber = 2;
    adjacentEntry.specialLink = 2;
    expectStringError([&]() { adjacentOrigins.checkConsistency(); });
  }

  // PASS permits repeated occupancy, preserves duplicates, and two pre-threshold passes settle an empty ledger.
  {
    CollapseGoState state(CollapseGoConfig::allOne(9));
    PositionalSuperkoKey empty(state.getPosition().getBoardSize(),state.getPosition().getRowMajorOccupancy());

    CollapseGoApplyResult first = playPass(state);
    testAssert(first.positionalSuperkoAppends == 1);
    testAssert(!first.settlementTriggered);
    testAssert(state.getAtomicActionCount() == 1);
    testAssert(state.getConsecutivePasses() == 1);
    testAssert(state.getActor() == P_WHITE);
    testAssert(state.getRevision() == 1);
    testAssert(state.getLogPosition() == 1);
    testAssert(state.getPositionalSuperkoHistory().size() == 2);
    testAssert(state.getPositionalSuperkoHistory().at(0) == empty);
    testAssert(state.getPositionalSuperkoHistory().at(1) == empty);

    CollapseGoApplyResult second = playPass(state);
    testAssert(second.positionalSuperkoAppends == 1);
    testAssert(second.settlementTriggered);
    testAssert(second.settlementReason == CollapseGoSettlementReason::PRE_THRESHOLD_TWO_PASSES);
    testAssert(!second.terminalScoreEventEmitted);
    testAssert(state.getPhase() == CollapseGoPhase::ORDINARY_PLAY);
    testAssert(state.isSettlementCompleted());
    testAssert(state.getActor() == P_BLACK);
    testAssert(state.getAtomicActionCount() == 2);
    testAssert(state.getConsecutivePasses() == 0);
    testAssert(state.getPositionalSuperkoHistory().size() == 3);
    testAssert(state.getPositionalSuperkoHistory().at(2) == empty);
    testAssert(state.getRevision() == 2);
    testAssert(state.getLogPosition() == 2);
    testAssert(state.getSettledLedgerCount() == 0);
    state.checkConsistency();
    for(Player pla: {P_BLACK,P_WHITE}) {
      testAssert(state.getRemainingQuota(pla,CollapseGoAbility::IMMORTAL) == 0);
      testAssert(state.getRemainingQuota(pla,CollapseGoAbility::DOUBLE_MOVE) == 0);
      testAssert(state.getRemainingQuota(pla,CollapseGoAbility::EIGHTWAY) == 0);
      testAssert(state.getUsedQuota(pla,CollapseGoAbility::IMMORTAL) == 0);
      testAssert(state.getUsedQuota(pla,CollapseGoAbility::DOUBLE_MOVE) == 0);
      testAssert(state.getUsedQuota(pla,CollapseGoAbility::EIGHTWAY) == 0);
      testAssert(state.getExpiredQuota(pla,CollapseGoAbility::IMMORTAL) == 1);
      testAssert(state.getExpiredQuota(pla,CollapseGoAbility::DOUBLE_MOVE) == 1);
      testAssert(state.getExpiredQuota(pla,CollapseGoAbility::EIGHTWAY) == 1);
    }
  }

  // Empty-ledger settlement expires every remaining component for arbitrary nonnegative quotas.
  {
    CollapseGoConfig config(9,CollapseGoQuotas(2,0,3),CollapseGoQuotas(0,4,0));
    CollapseGoState state(config);
    playPass(state);
    playPass(state);
    testAssert(state.getPhase() == CollapseGoPhase::ORDINARY_PLAY);
    for(CollapseGoAbility ability: {
      CollapseGoAbility::IMMORTAL,
      CollapseGoAbility::DOUBLE_MOVE,
      CollapseGoAbility::EIGHTWAY,
    }) {
      for(Player pla: {P_BLACK,P_WHITE}) {
        testAssert(state.getRemainingQuota(pla,ability) == 0);
        testAssert(state.getUsedQuota(pla,ability) == 0);
        testAssert(state.getExpiredQuota(pla,ability) == state.getInitialQuota(pla,ability));
      }
    }
    testAssert(state.getExpiredQuota(P_BLACK,CollapseGoAbility::IMMORTAL) == 2);
    testAssert(state.getExpiredQuota(P_BLACK,CollapseGoAbility::DOUBLE_MOVE) == 0);
    testAssert(state.getExpiredQuota(P_BLACK,CollapseGoAbility::EIGHTWAY) == 3);
    testAssert(state.getExpiredQuota(P_WHITE,CollapseGoAbility::IMMORTAL) == 0);
    testAssert(state.getExpiredQuota(P_WHITE,CollapseGoAbility::DOUBLE_MOVE) == 4);
    testAssert(state.getExpiredQuota(P_WHITE,CollapseGoAbility::EIGHTWAY) == 0);
    state.checkConsistency();
  }

  // Each supported size reaches its exact threshold without carrying a PASS into ordinary play.
  {
    for(int boardSize: {9,13,19}) {
      CollapseGoState state(CollapseGoConfig::allZero(boardSize));
      int threshold = state.getConfig().getThreshold();
      for(int i = 0; i < threshold / 2; i++) {
        CollapseGoApplyResult passResult = playPass(state);
        testAssert(!passResult.settlementTriggered);
        int x = i % boardSize;
        int y = i / boardSize;
        CollapseGoApplyResult moveResult = playNormal(state,x,y);
        if(i + 1 < threshold / 2) {
          testAssert(!moveResult.settlementTriggered);
          testAssert(state.getPhase() == CollapseGoPhase::COLLAPSE_PLAY);
        }
        else {
          testAssert(moveResult.settlementTriggered);
          testAssert(moveResult.settlementReason == CollapseGoSettlementReason::THRESHOLD);
        }
      }
      testAssert(state.getAtomicActionCount() == threshold);
      testAssert(state.getPhase() == CollapseGoPhase::ORDINARY_PLAY);
      testAssert(state.getConsecutivePasses() == 0);
      testAssert(state.getActor() == P_BLACK);
      testAssert(state.getPositionalSuperkoHistory().size() == static_cast<size_t>(threshold + 1));
    }
  }

  // Threshold trigger precedence wins when action T is also the second PASS, and Double spans T-1/T atomically.
  {
    CollapseGoState passAtThreshold(CollapseGoConfig::allZero(9));
    for(int i = 0; i < 16; i++) {
      playPass(passAtThreshold);
      playNormal(passAtThreshold,i % 9,i / 9);
    }
    testAssert(passAtThreshold.getAtomicActionCount() == 32);
    CollapseGoApplyResult action33 = playPass(passAtThreshold);
    testAssert(!action33.settlementTriggered);
    CollapseGoApplyResult action34 = playPass(passAtThreshold);
    testAssert(action34.settlementTriggered);
    testAssert(action34.settlementReason == CollapseGoSettlementReason::THRESHOLD);

    CollapseGoState doubleBoundary(CollapseGoConfig::allOne(9));
    for(int i = 0; i < 16; i++) {
      playPass(doubleBoundary);
      playNormal(doubleBoundary,i % 9,i / 9);
    }
    testAssert(doubleBoundary.getAtomicActionCount() == 32);
    CollapseGoApplyResult doubleStart = playDoubleStart(doubleBoundary,8,8);
    testAssert(!doubleStart.settlementTriggered);
    testAssert(doubleBoundary.getAtomicActionCount() == 33);
    testAssert(doubleBoundary.getActor() == P_BLACK);
    testAssert(doubleBoundary.getPendingDouble().has_value());
    testAssert(doubleBoundary.getPendingDouble()->originActionNumber == 33);
    testAssert(doubleBoundary.getPendingDouble()->specialLink == 33);
    expectRejectedAtomically(
      doubleBoundary,P_BLACK,specialAction(GameActionKind::DOUBLE_START,9,8,7),
      CollapseGoApplyError::DOUBLE_CONTINUATION_KIND_FORBIDDEN,true
    );

    CollapseGoApplyResult continuation = playNormal(doubleBoundary,8,7);
    testAssert(continuation.settlementTriggered);
    testAssert(continuation.settlementReason == CollapseGoSettlementReason::THRESHOLD);
    testAssert(continuation.positionalSuperkoAppends == 2);
    testAssert(continuation.settlementSteps.size() == 1);
    testAssert(continuation.settlementSteps[0].originActionNumber == 33);
    testAssert(continuation.settlementSteps[0].noOp);
    testAssert(!continuation.settlementSteps[0].abilityDeactivated);
    testAssert(doubleBoundary.getAtomicActionCount() == 34);
    testAssert(doubleBoundary.getRevision() == 34);
    testAssert(doubleBoundary.getLogPosition() == 35);
    testAssert(doubleBoundary.getSettledLedgerCount() == 1);
    testAssert(doubleBoundary.getPhase() == CollapseGoPhase::ORDINARY_PLAY);
    testAssert(doubleBoundary.getActor() == P_WHITE);
    testAssert(!doubleBoundary.getPendingDouble().has_value());
    testAssert(doubleBoundary.getPositionalSuperkoHistory().size() == 36);
    const CollapseGoStoneSource& continuationSource = doubleBoundary.getPosition().getCell(8,7).getSource();
    testAssert(continuationSource.originActionNumber == 34);
    testAssert(continuationSource.originKind == GameActionKind::NORMAL);
    testAssert(!continuationSource.specialLink.has_value());

    CollapseGoState doublePassBoundary(CollapseGoConfig::allOne(9));
    for(int i = 0; i < 16; i++) {
      playPass(doublePassBoundary);
      playNormal(doublePassBoundary,i % 9,i / 9);
    }
    testAssert(doublePassBoundary.getAtomicActionCount() == 32);
    playDoubleStart(doublePassBoundary,8,8);
    CollapseGoApplyResult passContinuation = playPass(doublePassBoundary);
    testAssert(passContinuation.settlementTriggered);
    testAssert(passContinuation.settlementReason == CollapseGoSettlementReason::THRESHOLD);
    testAssert(passContinuation.positionalSuperkoAppends == 2);
    testAssert(passContinuation.settlementSteps.size() == 1);
    testAssert(passContinuation.settlementSteps[0].originActionNumber == 33);
    testAssert(passContinuation.settlementSteps[0].noOp);
    testAssert(!passContinuation.settlementSteps[0].abilityDeactivated);
    testAssert(doublePassBoundary.getAtomicActionCount() == 34);
    testAssert(doublePassBoundary.getRevision() == 34);
    testAssert(doublePassBoundary.getLogPosition() == 35);
    testAssert(doublePassBoundary.getSettledLedgerCount() == 1);
    testAssert(doublePassBoundary.getActor() == P_WHITE);
    testAssert(doublePassBoundary.getPhase() == CollapseGoPhase::ORDINARY_PLAY);
    testAssert(doublePassBoundary.getConsecutivePasses() == 0);
    testAssert(!doublePassBoundary.getPendingDouble().has_value());
    testAssert(doublePassBoundary.getPositionalSuperkoHistory().size() == 36);

    CollapseGoState tooLate(CollapseGoConfig::allOne(9));
    playDoubleStart(tooLate,8,8);
    playNormal(tooLate,8,7);
    for(int i = 0; i < 15; i++) {
      playPass(tooLate);
      playNormal(tooLate,i % 9,i / 9);
    }
    testAssert(tooLate.getAtomicActionCount() == 32);
    playNormal(tooLate,7,7);
    testAssert(tooLate.getAtomicActionCount() == 33);
    testAssert(tooLate.getActor() == P_BLACK);
    testAssert(tooLate.getRemainingQuota(P_BLACK,CollapseGoAbility::DOUBLE_MOVE) == 0);
    testAssert(!tooLate.getPosition().isEmpty(8,8));
    expectRejectedAtomically(
      tooLate,P_BLACK,specialAction(GameActionKind::DOUBLE_START,9,8,8),
      CollapseGoApplyError::DOUBLE_THRESHOLD,true
    );
  }

  // Double start and NORMAL continuation are separate full N4 transactions with distinct source identities.
  {
    CollapseGoState state(CollapseGoConfig::allOne(9));
    playNormal(state,1,0); playNormal(state,1,1);
    playNormal(state,0,1); playNormal(state,8,8);
    playNormal(state,2,1); playNormal(state,8,7);

    CollapseGoApplyResult start = playDoubleStart(state,7,7);
    testAssert(start.positionalSuperkoAppends == 1);
    testAssert(start.capturedStones.empty());
    testAssert(state.getAtomicActionCount() == 7);
    testAssert(state.getActor() == P_BLACK);
    testAssert(state.getConsecutivePasses() == 0);
    testAssert(state.getPendingDouble().has_value());
    testAssert(state.getPendingDouble()->owner == P_BLACK);
    testAssert(state.getPendingDouble()->specialLink == 7);
    testAssert(state.getRemainingQuota(P_BLACK,CollapseGoAbility::DOUBLE_MOVE) == 0);
    testAssert(state.getUsedQuota(P_BLACK,CollapseGoAbility::DOUBLE_MOVE) == 1);
    testAssert(state.getLedger().size() == 1);
    const CollapseGoLedgerEntry& pendingEntry = state.getLedger().at(0);
    testAssert(pendingEntry.specialLink == 7);
    testAssert(pendingEntry.originActionNumber == 7);
    testAssert(pendingEntry.owner == P_BLACK);
    testAssert(pendingEntry.originKind == GameActionKind::DOUBLE_START);
    testAssert(pendingEntry.sourcePoint == 7 + 7 * 9);
    testAssert(pendingEntry.abilityState == CollapseGoLedgerAbilityState::CONSUMED);
    testAssert(pendingEntry.stoneState == CollapseGoLedgerStoneState::ON_BOARD);
    testAssert(pendingEntry.settlementState == CollapseGoLedgerSettlementState::PENDING);
    testAssert(pendingEntry.tombstone);
    const CollapseGoStoneSource& startSource = state.getPosition().getCell(7,7).getSource();
    testAssert(startSource.originActionNumber == 7);
    testAssert(startSource.originKind == GameActionKind::DOUBLE_START);
    testAssert(startSource.specialLink.has_value() && *startSource.specialLink == 7);

    CollapseGoApplyResult continuation = playNormal(state,1,2);
    testAssert(continuation.capturedStones.size() == 1);
    testAssert(continuation.capturedStones[0] == Location::getLoc(1,1,9));
    testAssert(!continuation.settlementTriggered);
    testAssert(state.getAtomicActionCount() == 8);
    testAssert(state.getActor() == P_WHITE);
    testAssert(!state.getPendingDouble().has_value());
    testAssert(state.getPosition().getColor(1,1) == C_EMPTY);
    const CollapseGoStoneSource& continuationSource = state.getPosition().getCell(1,2).getSource();
    testAssert(continuationSource.originActionNumber == 8);
    testAssert(continuationSource.originKind == GameActionKind::NORMAL);
    testAssert(!continuationSource.specialLink.has_value());
    testAssert(state.getLedger().at(0).stoneState == CollapseGoLedgerStoneState::ON_BOARD);
    testAssert(state.getPositionalSuperkoHistory().size() == 9);
    state.checkConsistency();
  }

  // Frozen singleton fixture: Double start, PASS continuation, opponent PASS, then one no-op settlement pop.
  {
    CollapseGoState state(CollapseGoConfig::allOne(19));
    PositionalSuperkoKey empty(19,state.getPosition().getRowMajorOccupancy());
    CollapseGoApplyResult start = playDoubleStart(state,9,9);
    testAssert(start.positionalSuperkoAppends == 1);
    testAssert(state.getAtomicActionCount() == 1);
    testAssert(state.getRevision() == 1);
    testAssert(state.getLogPosition() == 1);
    testAssert(state.getActor() == P_BLACK);
    testAssert(state.getPendingDouble().has_value());
    const CollapseGoLedgerEntry& afterStart = state.getLedger().at(0);
    testAssert(afterStart.abilityState == CollapseGoLedgerAbilityState::CONSUMED);
    testAssert(afterStart.stoneState == CollapseGoLedgerStoneState::ON_BOARD);
    testAssert(afterStart.settlementState == CollapseGoLedgerSettlementState::PENDING);
    testAssert(afterStart.tombstone);

    expectRejectedAtomically(
      state,P_WHITE,specialAction(GameActionKind::IMMORTAL,19,0,0),
      CollapseGoApplyError::WRONG_ACTOR,true
    );
    expectRejectedAtomically(
      state,P_BLACK,specialAction(GameActionKind::IMMORTAL,19,0,0),
      CollapseGoApplyError::DOUBLE_CONTINUATION_KIND_FORBIDDEN,true
    );
    expectRejectedAtomically(
      state,P_BLACK,specialAction(GameActionKind::DOUBLE_START,19,9,9),
      CollapseGoApplyError::DOUBLE_CONTINUATION_KIND_FORBIDDEN,true
    );
    expectRejectedAtomically(
      state,P_BLACK,normalAction(19,9,9),CollapseGoApplyError::POINT_OCCUPIED,true
    );

    CollapseGoApplyResult continuation = playPass(state);
    testAssert(continuation.positionalSuperkoAppends == 1);
    testAssert(!continuation.settlementTriggered);
    testAssert(state.getAtomicActionCount() == 2);
    testAssert(state.getActor() == P_WHITE);
    testAssert(state.getConsecutivePasses() == 1);
    testAssert(!state.getPendingDouble().has_value());

    CollapseGoApplyResult trigger = playPass(state);
    testAssert(trigger.settlementTriggered);
    testAssert(trigger.settlementReason == CollapseGoSettlementReason::PRE_THRESHOLD_TWO_PASSES);
    testAssert(trigger.positionalSuperkoAppends == 2);
    testAssert(trigger.settlementSteps.size() == 1);
    testAssert(trigger.settlementSteps[0].specialLink == 1);
    testAssert(trigger.settlementSteps[0].originActionNumber == 1);
    testAssert(trigger.settlementSteps[0].owner == P_BLACK);
    testAssert(trigger.settlementSteps[0].originKind == GameActionKind::DOUBLE_START);
    testAssert(trigger.settlementSteps[0].sourcePoint == 180);
    testAssert(trigger.settlementSteps[0].noOp);
    testAssert(!trigger.settlementSteps[0].abilityDeactivated);
    testAssert(state.getAtomicActionCount() == 3);
    testAssert(state.getRevision() == 3);
    testAssert(state.getLogPosition() == 4);
    testAssert(state.getSettledLedgerCount() == 1);
    testAssert(state.getActor() == P_BLACK);
    testAssert(state.getPhase() == CollapseGoPhase::ORDINARY_PLAY);
    testAssert(state.getConsecutivePasses() == 0);
    testAssert(!state.getPendingDouble().has_value());
    const CollapseGoLedgerEntry& settled = state.getLedger().at(0);
    testAssert(settled.abilityState == CollapseGoLedgerAbilityState::INACTIVE);
    testAssert(settled.stoneState == CollapseGoLedgerStoneState::ON_BOARD);
    testAssert(settled.settlementState == CollapseGoLedgerSettlementState::SETTLED);
    testAssert(settled.tombstone);
    testAssert(state.getRemainingQuota(P_BLACK,CollapseGoAbility::DOUBLE_MOVE) == 0);
    testAssert(state.getUsedQuota(P_BLACK,CollapseGoAbility::DOUBLE_MOVE) == 1);
    testAssert(state.getExpiredQuota(P_BLACK,CollapseGoAbility::DOUBLE_MOVE) == 0);
    testAssert(state.getPositionalSuperkoHistory().size() == 5);
    testAssert(state.getPositionalSuperkoHistory().at(0) == empty);
    for(size_t i = 2; i < 5; i++)
      testAssert(state.getPositionalSuperkoHistory().at(i) == state.getPositionalSuperkoHistory().at(1));
    state.checkConsistency();
  }

  // Double start resets an earlier ordinary PASS before a PASS continuation begins a fresh streak.
  {
    CollapseGoState state(CollapseGoConfig::allOne(9));
    CollapseGoApplyResult ordinaryPass = playPass(state);
    testAssert(!ordinaryPass.settlementTriggered);
    testAssert(state.getConsecutivePasses() == 1);
    testAssert(state.getActor() == P_WHITE);

    CollapseGoApplyResult start = playDoubleStart(state,4,4);
    testAssert(!start.settlementTriggered);
    testAssert(state.getConsecutivePasses() == 0);
    testAssert(state.getActor() == P_WHITE);
    testAssert(state.getPendingDouble().has_value());

    CollapseGoApplyResult continuation = playPass(state);
    testAssert(!continuation.settlementTriggered);
    testAssert(continuation.settlementReason == CollapseGoSettlementReason::NONE);
    testAssert(continuation.positionalSuperkoAppends == 1);
    testAssert(state.getAtomicActionCount() == 3);
    testAssert(state.getConsecutivePasses() == 1);
    testAssert(state.getActor() == P_BLACK);
    testAssert(state.getPhase() == CollapseGoPhase::COLLAPSE_PLAY);
    testAssert(!state.getPendingDouble().has_value());
    testAssert(state.getSettledLedgerCount() == 0);
    state.checkConsistency();
  }

  // A failed NORMAL continuation preserves the complete pending obligation and all committed Double metadata.
  {
    CollapseGoState state(CollapseGoConfig::allOne(9));
    playNormal(state,8,8); playNormal(state,1,2);
    playNormal(state,8,7); playNormal(state,3,2);
    playNormal(state,7,8); playNormal(state,2,1);
    playNormal(state,7,7); playNormal(state,2,3);
    playDoubleStart(state,0,0);
    testAssert(state.getPendingDouble().has_value());
    expectRejectedAtomically(
      state,P_WHITE,GameAction::fromCanvas(GameActionKind::EIGHTWAY,0,0),
      CollapseGoApplyError::POINT_OFF_BOARD,true
    );
    expectRejectedAtomically(
      state,P_BLACK,normalAction(9,2,2),CollapseGoApplyError::SUICIDE,true
    );
    testAssert(state.getPendingDouble().has_value());
    testAssert(state.getPendingDouble()->originActionNumber == 9);
    testAssert(state.getLedger().size() == 1);
    testAssert(state.getUsedQuota(P_BLACK,CollapseGoAbility::DOUBLE_MOVE) == 1);
    playPass(state);
    testAssert(!state.getPendingDouble().has_value());
    testAssert(state.getActor() == P_WHITE);
  }

  // Pending Double rejects Eightway before quota and point mechanics are consulted.
  {
    CollapseGoConfig config(9,CollapseGoQuotas(0,1,0),CollapseGoQuotas());
    CollapseGoState state(config);
    playDoubleStart(state,4,4);
    expectRejectedAtomically(
      state,P_BLACK,specialAction(GameActionKind::EIGHTWAY,9,4,4),
      CollapseGoApplyError::DOUBLE_CONTINUATION_KIND_FORBIDDEN,true
    );
    testAssert(state.getRemainingQuota(P_BLACK,CollapseGoAbility::EIGHTWAY) == 0);
    testAssert(state.getPosition().getColor(4,4) == C_BLACK);
    playPass(state);
  }

  // Capturing a Double source updates its append-only tombstone, whose later settlement step remains a no-op.
  {
    CollapseGoState state(CollapseGoConfig::allOne(9));
    playDoubleStart(state,1,1);
    playNormal(state,8,8);
    playNormal(state,1,0); playNormal(state,8,7);
    playNormal(state,0,1); playNormal(state,7,8);
    playNormal(state,2,1); playNormal(state,7,7);
    CollapseGoApplyResult capture = playNormal(state,1,2);
    testAssert(capture.capturedStones.size() == 1);
    testAssert(capture.capturedStones[0] == Location::getLoc(1,1,9));
    testAssert(state.getPosition().getColor(1,1) == C_EMPTY);
    testAssert(state.getLedger().at(0).stoneState == CollapseGoLedgerStoneState::CAPTURED);
    testAssert(state.getRemainingQuota(P_BLACK,CollapseGoAbility::DOUBLE_MOVE) == 0);
    testAssert(state.getUsedQuota(P_BLACK,CollapseGoAbility::DOUBLE_MOVE) == 1);

    playPass(state);
    CollapseGoApplyResult trigger = playPass(state);
    testAssert(trigger.settlementTriggered);
    testAssert(trigger.settlementSteps.size() == 1);
    testAssert(trigger.settlementSteps[0].originActionNumber == 1);
    testAssert(trigger.settlementSteps[0].noOp);
    testAssert(!trigger.settlementSteps[0].abilityDeactivated);
    testAssert(state.getLedger().at(0).stoneState == CollapseGoLedgerStoneState::CAPTURED);
    testAssert(state.getLedger().at(0).settlementState == CollapseGoLedgerSettlementState::SETTLED);
    testAssert(state.getSettledLedgerCount() == 1);
    state.checkConsistency();
  }

  // A later Double start may capture an older Double source; mixed tombstones still pop by global age.
  {
    CollapseGoState state(CollapseGoConfig::allOne(9));
    playDoubleStart(state,1,1);
    playNormal(state,8,8);
    playNormal(state,1,0); playNormal(state,8,7);
    playNormal(state,0,1); playNormal(state,7,8);
    playNormal(state,2,1); playNormal(state,7,7);

    CollapseGoApplyResult capturingStart = playDoubleStart(state,1,2);
    testAssert(capturingStart.capturedStones.size() == 1);
    testAssert(capturingStart.capturedStones[0] == Location::getLoc(1,1,9));
    testAssert(capturingStart.positionalSuperkoAppends == 1);
    testAssert(state.getActor() == P_WHITE);
    testAssert(state.getPendingDouble().has_value());
    testAssert(state.getPendingDouble()->originActionNumber == 9);
    testAssert(state.getLedger().size() == 2);
    testAssert(state.getLedger().at(0).originActionNumber == 1);
    testAssert(state.getLedger().at(0).stoneState == CollapseGoLedgerStoneState::CAPTURED);
    testAssert(state.getLedger().at(1).originActionNumber == 9);
    testAssert(state.getLedger().at(1).stoneState == CollapseGoLedgerStoneState::ON_BOARD);
    const CollapseGoStoneSource& source = state.getPosition().getCell(1,2).getSource();
    testAssert(source.originActionNumber == 9);
    testAssert(source.originKind == GameActionKind::DOUBLE_START);
    testAssert(source.specialLink.has_value() && *source.specialLink == 9);

    playNormal(state,6,6);
    playPass(state);
    CollapseGoApplyResult trigger = playPass(state);
    testAssert(trigger.settlementTriggered);
    testAssert(trigger.settlementSteps.size() == 2);
    testAssert(trigger.settlementSteps[0].originActionNumber == 9);
    testAssert(trigger.settlementSteps[1].originActionNumber == 1);
    for(const CollapseGoSettlementStep& step: trigger.settlementSteps) {
      testAssert(step.noOp);
      testAssert(!step.abilityDeactivated);
    }
    testAssert(trigger.positionalSuperkoAppends == 3);
    testAssert(state.getLedger().at(0).stoneState == CollapseGoLedgerStoneState::CAPTURED);
    testAssert(state.getLedger().at(1).stoneState == CollapseGoLedgerStoneState::ON_BOARD);
    testAssert(state.getSettledLedgerCount() == 2);
    testAssert(state.getAtomicActionCount() == 12);
    testAssert(state.getLogPosition() == 14);
    testAssert(state.getPositionalSuperkoHistory().size() == 15);
    state.checkConsistency();
  }

  // Experimental quotas above one retain every Double and settle the global ledger newest-to-oldest.
  {
    CollapseGoConfig config(9,CollapseGoQuotas(0,2,0),CollapseGoQuotas(0,2,0));
    CollapseGoState state(config);
    playDoubleStart(state,0,0);
    playNormal(state,1,0);
    playDoubleStart(state,8,8);
    playPass(state);
    playNormal(state,4,4);
    playDoubleStart(state,7,8);
    playNormal(state,6,8);
    playDoubleStart(state,0,1);
    playNormal(state,1,1);
    playPass(state);
    CollapseGoApplyResult trigger = playPass(state);

    testAssert(trigger.settlementTriggered);
    testAssert(trigger.settlementReason == CollapseGoSettlementReason::PRE_THRESHOLD_TWO_PASSES);
    testAssert(trigger.settlementSteps.size() == 4);
    const int64_t expectedNewestFirst[4] = {8,6,3,1};
    for(size_t i = 0; i < trigger.settlementSteps.size(); i++) {
      testAssert(trigger.settlementSteps[i].originActionNumber == expectedNewestFirst[i]);
      testAssert(trigger.settlementSteps[i].specialLink == expectedNewestFirst[i]);
      testAssert(trigger.settlementSteps[i].noOp);
      testAssert(!trigger.settlementSteps[i].abilityDeactivated);
    }
    testAssert(trigger.positionalSuperkoAppends == 5);
    testAssert(state.getLedger().size() == 4);
    const int64_t expectedOldestFirst[4] = {1,3,6,8};
    for(size_t i = 0; i < state.getLedger().size(); i++) {
      const CollapseGoLedgerEntry& entry = state.getLedger().at(i);
      testAssert(entry.originActionNumber == expectedOldestFirst[i]);
      testAssert(entry.abilityState == CollapseGoLedgerAbilityState::INACTIVE);
      testAssert(entry.stoneState == CollapseGoLedgerStoneState::ON_BOARD);
      testAssert(entry.settlementState == CollapseGoLedgerSettlementState::SETTLED);
      testAssert(entry.tombstone);
    }
    testAssert(state.getAtomicActionCount() == 11);
    testAssert(state.getRevision() == 11);
    testAssert(state.getSettledLedgerCount() == 4);
    testAssert(state.getLogPosition() == 15);
    testAssert(state.getPositionalSuperkoHistory().size() == 16);
    testAssert(state.getActor() == P_WHITE);
    testAssert(state.getPhase() == CollapseGoPhase::ORDINARY_PLAY);
    for(Player pla: {P_BLACK,P_WHITE}) {
      testAssert(state.getInitialQuota(pla,CollapseGoAbility::DOUBLE_MOVE) == 2);
      testAssert(state.getRemainingQuota(pla,CollapseGoAbility::DOUBLE_MOVE) == 0);
      testAssert(state.getUsedQuota(pla,CollapseGoAbility::DOUBLE_MOVE) == 2);
      testAssert(state.getExpiredQuota(pla,CollapseGoAbility::DOUBLE_MOVE) == 0);
    }
    for(size_t i = 12; i < 16; i++)
      testAssert(state.getPositionalSuperkoHistory().at(i) == state.getPositionalSuperkoHistory().at(11));
    state.checkConsistency();
  }

  // Experimental quotas above one retain every Eightway source and settle them newest-to-oldest.
  {
    CollapseGoConfig config(9,CollapseGoQuotas(0,0,2),CollapseGoQuotas());
    CollapseGoState state(config);
    playEightway(state,0,0);
    playNormal(state,8,8);
    playEightway(state,1,1);
    testAssert(state.getArmedEightwaySources() == vector<int>({0,10}));
    testAssert(state.getRemainingQuota(P_BLACK,CollapseGoAbility::EIGHTWAY) == 0);
    testAssert(state.getUsedQuota(P_BLACK,CollapseGoAbility::EIGHTWAY) == 2);
    testAssert(state.getLedger().size() == 2);
    testAssert(state.getLedger().at(0).originActionNumber == 1);
    testAssert(state.getLedger().at(1).originActionNumber == 3);
    CollapseGoTopology armedTopology = CollapseGoTopology::fullScan(
      state.getPosition(),state.getArmedImmortalAnchors(),state.getArmedEightwaySources()
    );
    testAssert(armedTopology.getGroupAt(0).stones == vector<int>({0,10}));

    playPass(state);
    CollapseGoApplyResult trigger = playPass(state);
    testAssert(trigger.settlementTriggered);
    testAssert(trigger.settlementSteps.size() == 2);
    testAssert(trigger.settlementSteps[0].originActionNumber == 3);
    testAssert(trigger.settlementSteps[1].originActionNumber == 1);
    for(const CollapseGoSettlementStep& step: trigger.settlementSteps) {
      testAssert(step.originKind == GameActionKind::EIGHTWAY);
      testAssert(step.abilityDeactivated && !step.noOp);
      testAssert(step.removalBatches.empty());
    }
    testAssert(trigger.settlementSteps[0].stableOccupancy ==
      trigger.settlementSteps[1].stableOccupancy);
    testAssert(trigger.positionalSuperkoAppends == 3);
    testAssert(state.getArmedEightwaySources().empty());
    testAssert(state.getAtomicActionCount() == 5);
    testAssert(state.getLogPosition() == 7);
    testAssert(state.getPositionalSuperkoHistory().size() == 8);
    testAssert(state.getActor() == P_WHITE);
    for(size_t index = 0; index < state.getLedger().size(); index++) {
      const CollapseGoLedgerEntry& entry = state.getLedger().at(index);
      testAssert(entry.abilityState == CollapseGoLedgerAbilityState::INACTIVE);
      testAssert(entry.stoneState == CollapseGoLedgerStoneState::ON_BOARD);
      testAssert(entry.settlementState == CollapseGoLedgerSettlementState::SETTLED);
      testAssert(entry.tombstone);
    }
    testAssert(state.getExpiredQuota(P_BLACK,CollapseGoAbility::EIGHTWAY) == 0);
    state.checkConsistency();
  }

  // A NORMAL action captures multiple independent N4 groups in one committed transition.
  {
    CollapseGoState state(CollapseGoConfig::allZero(9));
    playNormal(state,0,2); playNormal(state,1,2);
    playNormal(state,1,1); playNormal(state,3,2);
    playNormal(state,1,3); playNormal(state,8,8);
    playNormal(state,4,2); playNormal(state,8,7);
    playNormal(state,3,1); playNormal(state,7,8);
    playNormal(state,3,3); playNormal(state,7,7);

    CollapseGoStoneSource survivingBlackSource = state.getPosition().getCell(0,2).getSource();
    CollapseGoStoneSource survivingWhiteSource = state.getPosition().getCell(8,8).getSource();
    CollapseGoApplyResult capture = playNormal(state,2,2);
    testAssert(capture.capturedStones.size() == 2);
    testAssert(capture.capturedStones[0] == Location::getLoc(1,2,9));
    testAssert(capture.capturedStones[1] == Location::getLoc(3,2,9));
    const CollapseGoPosition& position = state.getPosition();
    testAssert(position.getColor(1,2) == C_EMPTY);
    testAssert(position.getColor(3,2) == C_EMPTY);
    testAssert(position.getColor(2,2) == C_BLACK);
    testAssert(position.getCell(2,2).getSource().originActionNumber == 13);
    testAssert(position.getCell(2,2).getSource().originKind == GameActionKind::NORMAL);
    testAssert(!position.getCell(2,2).getSource().specialLink.has_value());
    testAssert(position.getCell(0,2).getSource() == survivingBlackSource);
    testAssert(position.getCell(8,8).getSource() == survivingWhiteSource);
    expectStringError([&]() { (void)position.getCell(1,2).getSource(); });
    expectStringError([&]() { (void)position.getCell(3,2).getSource(); });
    position.checkConsistency();
  }

  // Ordinary N4 suicide is rejected without any partial board, counter, or PSK mutation.
  {
    CollapseGoState state(CollapseGoConfig::allZero(9));
    playNormal(state,8,8); playNormal(state,1,2);
    playNormal(state,8,7); playNormal(state,3,2);
    playNormal(state,7,8); playNormal(state,2,1);
    playNormal(state,7,7); playNormal(state,2,3);
    expectRejectedAtomically(
      state,
      P_BLACK,
      normalAction(9,2,2),
      CollapseGoApplyError::SUICIDE,
      true
    );
  }

  // Double rejects an N4 suicide, while Eightway uses diagonal liberties and Immortal uses protection.
  {
    auto makeN4SurroundedState = []() {
      CollapseGoState state(CollapseGoConfig::allOne(9));
      playNormal(state,8,8); playNormal(state,1,2);
      playNormal(state,8,7); playNormal(state,3,2);
      playNormal(state,7,8); playNormal(state,2,1);
      playNormal(state,7,7); playNormal(state,2,3);
      return state;
    };

    CollapseGoState eightway(makeN4SurroundedState());
    expectRejectedAtomically(
      eightway,
      P_BLACK,
      specialAction(GameActionKind::DOUBLE_START,9,2,2),
      CollapseGoApplyError::SUICIDE,
      true
    );
    CollapseGoApplyResult placement = playEightway(eightway,2,2);
    testAssert(placement.capturedStones.empty());
    testAssert(eightway.getRemainingQuota(P_BLACK,CollapseGoAbility::EIGHTWAY) == 0);
    testAssert(eightway.getUsedQuota(P_BLACK,CollapseGoAbility::EIGHTWAY) == 1);
    testAssert(eightway.getArmedEightwaySources() == vector<int>({20}));
    CollapseGoTopology eightwayTopology = CollapseGoTopology::fullScan(
      eightway.getPosition(),
      eightway.getArmedImmortalAnchors(),
      eightway.getArmedEightwaySources()
    );
    testAssert(eightwayTopology.getGroupAt(20).liberties == vector<int>({10,12,28,30}));
    testAssert(!eightwayTopology.getGroupAt(20).protectedByImmortal);

    CollapseGoState immortal(makeN4SurroundedState());
    playImmortal(immortal,2,2);
    CollapseGoTopology immortalTopology = CollapseGoTopology::fullScan(
      immortal.getPosition(),
      immortal.getArmedImmortalAnchors(),
      immortal.getArmedEightwaySources()
    );
    const CollapseGoGroup& protectedGroup = immortalTopology.getGroupAt(20);
    testAssert(protectedGroup.liberties.empty());
    testAssert(protectedGroup.protectedByImmortal);
  }

  // Off-footprint, terminal, phase, actor, quota, and occupancy precedence is deterministic.
  {
    CollapseGoState state(CollapseGoConfig::allZero(9));
    GameAction offFootprint = GameAction::fromCanvas(GameActionKind::NORMAL,0,0);
    expectRejectedAtomically(
      state,P_WHITE,offFootprint,CollapseGoApplyError::POINT_OFF_BOARD,true
    );
    expectRejectedAtomically(
      state,P_WHITE,normalAction(9,4,4),CollapseGoApplyError::WRONG_ACTOR,true
    );

    playNormal(state,4,4);
    expectRejectedAtomically(
      state,P_WHITE,normalAction(9,4,4),CollapseGoApplyError::POINT_OCCUPIED,true
    );
    expectRejectedAtomically(
      state,P_WHITE,specialAction(GameActionKind::IMMORTAL,9,4,4),
      CollapseGoApplyError::QUOTA_EXHAUSTED,true
    );

    CollapseGoState supported(CollapseGoConfig::allOne(9));
    playNormal(supported,4,4);
    expectRejectedAtomically(
      supported,P_WHITE,specialAction(GameActionKind::IMMORTAL,9,4,4),
      CollapseGoApplyError::POINT_OCCUPIED,true
    );

    CollapseGoState ordinary(CollapseGoConfig::allOne(9));
    enterOrdinaryPlay(ordinary);
    expectRejectedAtomically(
      ordinary,P_WHITE,GameAction::fromCanvas(GameActionKind::EIGHTWAY,0,0),
      CollapseGoApplyError::POINT_OFF_BOARD,true
    );
    expectRejectedAtomically(
      ordinary,P_WHITE,specialAction(GameActionKind::EIGHTWAY,9,4,4),
      CollapseGoApplyError::INVALID_PHASE,true
    );
    playPass(ordinary);
    CollapseGoApplyResult terminalPass = playPass(ordinary);
    testAssert(terminalPass.terminalScoreEventEmitted);
    testAssert(ordinary.getPhase() == CollapseGoPhase::TERMINAL);
    expectRejectedAtomically(
      ordinary,P_WHITE,offFootprint,CollapseGoApplyError::POINT_OFF_BOARD,true
    );
    expectRejectedAtomically(
      ordinary,P_BLACK,normalAction(9,4,4),CollapseGoApplyError::TERMINAL_STATE,true
    );
  }

  // Exhausted specials are semantic rejections; an available Eightway is a supported placement.
  {
    CollapseGoState exhausted(CollapseGoConfig::allZero(9));
    for(GameActionKind kind: {
      GameActionKind::IMMORTAL,
      GameActionKind::DOUBLE_START,
      GameActionKind::EIGHTWAY,
    }) {
      expectRejectedAtomically(
        exhausted,P_BLACK,specialAction(kind,9,4,4),
        CollapseGoApplyError::QUOTA_EXHAUSTED,true
      );
    }

    CollapseGoState supported(CollapseGoConfig::allOne(9));
    CollapseGoApplyResult placement = playEightway(supported,4,4);
    testAssert(placement.accepted);
    testAssert(supported.getLedger().size() == 1);
    testAssert(supported.getLedger().at(0).originKind == GameActionKind::EIGHTWAY);
  }

  // A ko-shaped recapture is rejected by exact occupancy-only positional superko, not Board simple-ko legality.
  {
    CollapseGoState state(CollapseGoConfig::allZero(9));
    playNormal(state,1,2); playNormal(state,1,1);
    playNormal(state,3,2); playNormal(state,3,1);
    playNormal(state,2,3); playNormal(state,2,0);
    playNormal(state,8,8); playNormal(state,2,2);

    CollapseGoApplyResult capture = playNormal(state,2,1);
    testAssert(capture.capturedStones.size() == 1);
    testAssert(capture.capturedStones[0] == Location::getLoc(2,2,9));
    testAssert(state.getPosition().getColor(2,2) == C_EMPTY);
    testAssert(state.getPosition().getColor(2,1) == C_BLACK);
    expectRejectedAtomically(
      state,P_WHITE,normalAction(9,2,2),CollapseGoApplyError::POSITIONAL_SUPERKO,true
    );
  }

  // Double and Immortal recaptures both obey exact occupancy-only PSK and roll back atomically.
  {
    CollapseGoState state(CollapseGoConfig::allOne(9));
    playNormal(state,1,2); playNormal(state,1,1);
    playNormal(state,3,2); playNormal(state,3,1);
    playNormal(state,2,3); playNormal(state,2,0);
    playNormal(state,8,8); playNormal(state,2,2);
    playNormal(state,2,1);

    expectRejectedAtomically(
      state,P_WHITE,specialAction(GameActionKind::DOUBLE_START,9,2,2),
      CollapseGoApplyError::POSITIONAL_SUPERKO,true
    );
    expectRejectedAtomically(
      state,P_WHITE,specialAction(GameActionKind::IMMORTAL,9,2,2),
      CollapseGoApplyError::POSITIONAL_SUPERKO,true
    );
    expectRejectedAtomically(
      state,P_WHITE,specialAction(GameActionKind::EIGHTWAY,9,2,2),
      CollapseGoApplyError::POSITIONAL_SUPERKO,true
    );
    testAssert(state.getLedger().empty());
    testAssert(state.getRemainingQuota(P_WHITE,CollapseGoAbility::IMMORTAL) == 1);
    testAssert(state.getUsedQuota(P_WHITE,CollapseGoAbility::IMMORTAL) == 0);
    testAssert(state.getRemainingQuota(P_WHITE,CollapseGoAbility::EIGHTWAY) == 1);
    testAssert(state.getUsedQuota(P_WHITE,CollapseGoAbility::EIGHTWAY) == 0);
  }

  // The frozen true-eye prefix admits Eightway with 4, 3, 2, and 1 diagonal liberties, then rejects at zero.
  {
    CollapseGoState state(CollapseGoConfig::allOne(19));
    const pair<int,int> blackFillers[8] = {
      {18,18},{18,17},{17,18},{17,17},{16,18},{18,16},{16,16},{16,17},
    };
    const pair<int,int> whiteRing[8] = {
      {9,8},{8,9},{10,9},{9,10},{8,8},{10,8},{8,10},{10,10},
    };
    for(int index = 0; index < 8; index++) {
      playNormal(state,blackFillers[index].first,blackFillers[index].second);
      playNormal(state,whiteRing[index].first,whiteRing[index].second);
      if(index < 3)
        continue;

      if(index < 7) {
        CollapseGoState candidate(state);
        CollapseGoApplyResult placement = playEightway(candidate,9,9);
        testAssert(placement.accepted);
        CollapseGoTopology topology = CollapseGoTopology::fullScan(
          candidate.getPosition(),
          candidate.getArmedImmortalAnchors(),
          candidate.getArmedEightwaySources()
        );
        testAssert(topology.getGroupAt(180).liberties.size() == static_cast<size_t>(7-index));
        testAssert(candidate.getArmedEightwaySources() == vector<int>({180}));
      }
      else {
        expectRejectedAtomically(
          state,P_BLACK,specialAction(GameActionKind::EIGHTWAY,19,9,9),
          CollapseGoApplyError::SUICIDE,true
        );
      }
    }
    testAssert(state.getLedger().empty());
    testAssert(state.getRemainingQuota(P_BLACK,CollapseGoAbility::EIGHTWAY) == 1);
  }

  // Frozen true-eye fixture: only Immortal may occupy the zero-liberty center, then settlement removes it.
  {
    CollapseGoState state(CollapseGoConfig::allOne(19));
    playImmortalTrueEyePrefix(state);
    testAssert(state.getAtomicActionCount() == 16);
    expectRejectedAtomically(
      state,P_BLACK,normalAction(19,9,9),CollapseGoApplyError::SUICIDE,true
    );
    expectRejectedAtomically(
      state,P_BLACK,specialAction(GameActionKind::DOUBLE_START,19,9,9),
      CollapseGoApplyError::SUICIDE,true
    );
    expectRejectedAtomically(
      state,P_BLACK,specialAction(GameActionKind::EIGHTWAY,19,9,9),
      CollapseGoApplyError::SUICIDE,true
    );
    testAssert(state.getRemainingQuota(P_BLACK,CollapseGoAbility::EIGHTWAY) == 1);
    testAssert(state.getUsedQuota(P_BLACK,CollapseGoAbility::EIGHTWAY) == 0);
    testAssert(state.getLedger().empty());

    CollapseGoApplyResult placement = playImmortal(state,9,9);
    testAssert(placement.positionalSuperkoAppends == 1);
    testAssert(state.getAtomicActionCount() == 17);
    testAssert(state.getRevision() == 17);
    testAssert(state.getLogPosition() == 17);
    testAssert(state.getActor() == P_WHITE);
    testAssert(state.getRemainingQuota(P_BLACK,CollapseGoAbility::IMMORTAL) == 0);
    testAssert(state.getUsedQuota(P_BLACK,CollapseGoAbility::IMMORTAL) == 1);
    testAssert(state.getArmedImmortalAnchors() == vector<int>({180}));
    const CollapseGoLedgerEntry& armed = state.getLedger().at(0);
    testAssert(armed.originActionNumber == 17);
    testAssert(armed.originKind == GameActionKind::IMMORTAL);
    testAssert(armed.sourcePoint == 180);
    testAssert(armed.abilityState == CollapseGoLedgerAbilityState::ARMED);
    testAssert(armed.stoneState == CollapseGoLedgerStoneState::ON_BOARD);
    testAssert(armed.settlementState == CollapseGoLedgerSettlementState::PENDING);
    testAssert(!armed.tombstone);
    const CollapseGoStoneSource& source = state.getPosition().getCell(9,9).getSource();
    testAssert(source.originActionNumber == 17);
    testAssert(source.originKind == GameActionKind::IMMORTAL);
    testAssert(source.specialLink.has_value() && *source.specialLink == 17);
    CollapseGoTopology topology = CollapseGoTopology::fullScanN4(
      state.getPosition(),state.getArmedImmortalAnchors()
    );
    const CollapseGoGroup& protectedGroup = topology.getGroupAt(180);
    testAssert(protectedGroup.stones == vector<int>({180}));
    testAssert(protectedGroup.liberties.empty());
    testAssert(protectedGroup.protectedByImmortal);
    testAssert(state.getPositionalSuperkoHistory().size() == 18);
    testAssert(state.getPositionalSuperkoHistory().at(17) ==
      PositionalSuperkoKey(19,state.getPosition().getRowMajorOccupancy()));

    playPass(state);
    CollapseGoApplyResult trigger = playPass(state);
    testAssert(trigger.settlementTriggered);
    testAssert(trigger.settlementReason == CollapseGoSettlementReason::PRE_THRESHOLD_TWO_PASSES);
    testAssert(trigger.positionalSuperkoAppends == 2);
    testAssert(trigger.settlementSteps.size() == 1);
    const CollapseGoSettlementStep& step = trigger.settlementSteps[0];
    testAssert(step.stepIndex == 0);
    testAssert(step.specialLink == 17);
    testAssert(step.originKind == GameActionKind::IMMORTAL);
    testAssert(step.abilityDeactivated);
    testAssert(!step.noOp);
    testAssert(step.removalBatches.size() == 1);
    testAssert(step.removalBatches[0].blackStones == vector<Loc>({Location::getLoc(9,9,19)}));
    testAssert(step.removalBatches[0].whiteStones.empty());
    testAssert(step.stableOccupancy == state.getPositionalSuperkoHistory().at(16).getOccupancy());
    testAssert(step.positionalSuperkoHistoryIndex == 20);
    testAssert(state.getPosition().isEmpty(9,9));
    const CollapseGoLedgerEntry& settled = state.getLedger().at(0);
    testAssert(settled.abilityState == CollapseGoLedgerAbilityState::INACTIVE);
    testAssert(settled.stoneState == CollapseGoLedgerStoneState::CAPTURED);
    testAssert(settled.settlementState == CollapseGoLedgerSettlementState::SETTLED);
    testAssert(settled.tombstone);
    testAssert(state.getArmedImmortalAnchors().empty());
    testAssert(state.getAtomicActionCount() == 19);
    testAssert(state.getRevision() == 19);
    testAssert(state.getLogPosition() == 20);
    testAssert(state.getPositionalSuperkoHistory().size() == 21);
    testAssert(state.getPhase() == CollapseGoPhase::ORDINARY_PLAY);
    testAssert(state.getActor() == P_WHITE);
    testAssert(state.getConsecutivePasses() == 0);
    state.checkConsistency();

    playPass(state);
    expectRejectedAtomically(
      state,P_BLACK,normalAction(19,9,9),CollapseGoApplyError::SUICIDE,true
    );
  }

  // The mirrored reachable fixture exercises the white settlement-removal batch.
  {
    CollapseGoState state(CollapseGoConfig::allOne(19));
    playWhiteImmortalTrueEyePrefix(state);
    testAssert(state.getAtomicActionCount() == 17);
    testAssert(state.getActor() == P_WHITE);
    playImmortal(state,9,9);
    playPass(state);
    CollapseGoApplyResult trigger = playPass(state);
    testAssert(trigger.settlementTriggered);
    testAssert(trigger.settlementSteps.size() == 1);
    const CollapseGoSettlementStep& step = trigger.settlementSteps[0];
    testAssert(step.originActionNumber == 18);
    testAssert(step.owner == P_WHITE);
    testAssert(step.abilityDeactivated && !step.noOp);
    testAssert(step.removalBatches.size() == 1);
    testAssert(step.removalBatches[0].blackStones.empty());
    testAssert(step.removalBatches[0].whiteStones == vector<Loc>({Location::getLoc(9,9,19)}));
    testAssert(step.stableOccupancy == state.getPositionalSuperkoHistory().at(17).getOccupancy());
    testAssert(step.positionalSuperkoHistoryIndex == 21);
    testAssert(state.getPosition().isEmpty(9,9));
    testAssert(state.getLedger().at(0).abilityState == CollapseGoLedgerAbilityState::INACTIVE);
    testAssert(state.getLedger().at(0).stoneState == CollapseGoLedgerStoneState::CAPTURED);
    testAssert(state.getLedger().at(0).settlementState == CollapseGoLedgerSettlementState::SETTLED);
    testAssert(state.getLedger().at(0).tombstone);
    testAssert(state.getAtomicActionCount() == 20);
    testAssert(state.getRevision() == 20);
    testAssert(state.getLogPosition() == 21);
    testAssert(state.getSettledLedgerCount() == 1);
    testAssert(state.getPositionalSuperkoHistory().size() == 22);
    testAssert(state.getPhase() == CollapseGoPhase::ORDINARY_PLAY);
    testAssert(state.getActor() == P_BLACK);
    state.checkConsistency();
  }

  // A reachable Immortal placement-to-settlement episode is exact under all D4 maps and inverses.
  {
    const int inverseSymmetry[8] = {0,1,2,3,4,6,5,7};
    ImmortalD4Episode reference = runImmortalD4Episode(0);
    testAssert(reference.placementState.getArmedImmortalAnchors() == vector<int>({40}));
    testAssert(reference.settlementResult.settlementSteps.size() == 1);
    testAssert(reference.settlementResult.settlementSteps[0].removalBatches.size() == 1);
    testAssert(reference.settlementResult.settlementSteps[0].removalBatches[0].blackStones ==
      vector<Loc>({Location::getLoc(4,4,9)}));

    for(int symmetry = 0; symmetry < 8; symmetry++) {
      ImmortalD4Episode transformed = runImmortalD4Episode(symmetry);
      assertD4Actions(reference.actions,transformed.actions,9,symmetry);
      assertD4State(reference.placementState,transformed.placementState,symmetry);
      assertD4State(reference.finalState,transformed.finalState,symmetry);
      assertD4Settlement(reference.settlementResult,transformed.settlementResult,9,symmetry);

      int inverse = inverseSymmetry[symmetry];
      assertD4Actions(transformed.actions,reference.actions,9,inverse);
      assertD4State(transformed.placementState,reference.placementState,inverse);
      assertD4State(transformed.finalState,reference.finalState,inverse);
      assertD4Settlement(transformed.settlementResult,reference.settlementResult,9,inverse);
    }
  }

  // A reachable Eightway split and protection episode is exact under all D4 maps and inverses.
  {
    const int inverseSymmetry[8] = {0,1,2,3,4,6,5,7};
    ImmortalD4Episode reference = runEightwayD4Episode(0);
    testAssert(reference.placementState.getArmedImmortalAnchors() == vector<int>({10}));
    testAssert(reference.placementState.getArmedEightwaySources() == vector<int>({20}));
    CollapseGoTopology before = CollapseGoTopology::fullScan(
      reference.placementState.getPosition(),
      reference.placementState.getArmedImmortalAnchors(),
      reference.placementState.getArmedEightwaySources()
    );
    testAssert(before.getGroupAt(10).stones == vector<int>({10,12,20}));
    testAssert(before.getGroupAt(20).protectedByImmortal);
    CollapseGoTopology afterEightwayDeactivation = CollapseGoTopology::fullScan(
      reference.placementState.getPosition(),
      reference.placementState.getArmedImmortalAnchors(),
      vector<int>()
    );
    testAssert(afterEightwayDeactivation.getGroupAt(10).protectedByImmortal);
    testAssert(afterEightwayDeactivation.getGroupAt(12).stones == vector<int>({12}));
    testAssert(afterEightwayDeactivation.getGroupAt(12).liberties.empty());
    testAssert(!afterEightwayDeactivation.getGroupAt(12).protectedByImmortal);
    testAssert(afterEightwayDeactivation.getGroupAt(20).stones == vector<int>({20}));
    testAssert(afterEightwayDeactivation.getGroupAt(20).liberties.empty());
    testAssert(!afterEightwayDeactivation.getGroupAt(20).protectedByImmortal);
    testAssert(reference.settlementResult.settlementSteps.size() == 2);
    const CollapseGoSettlementStep& eightwayStep = reference.settlementResult.settlementSteps[0];
    testAssert(eightwayStep.originActionNumber == 9);
    testAssert(eightwayStep.originKind == GameActionKind::EIGHTWAY);
    testAssert(eightwayStep.abilityDeactivated && !eightwayStep.noOp);
    testAssert(eightwayStep.removalBatches.size() == 1);
    testAssert(eightwayStep.removalBatches[0].blackStones == vector<Loc>({
      Location::getLoc(3,1,9),Location::getLoc(2,2,9)
    }));
    testAssert(eightwayStep.removalBatches[0].whiteStones.empty());
    testAssert(eightwayStep.stableOccupancy[10] == static_cast<uint8_t>(C_BLACK));
    testAssert(eightwayStep.stableOccupancy[12] == static_cast<uint8_t>(C_EMPTY));
    testAssert(eightwayStep.stableOccupancy[20] == static_cast<uint8_t>(C_EMPTY));
    const CollapseGoSettlementStep& immortalStep = reference.settlementResult.settlementSteps[1];
    testAssert(immortalStep.originActionNumber == 1);
    testAssert(immortalStep.originKind == GameActionKind::IMMORTAL);
    testAssert(immortalStep.abilityDeactivated && !immortalStep.noOp);
    testAssert(immortalStep.removalBatches.empty());

    for(int symmetry = 0; symmetry < 8; symmetry++) {
      ImmortalD4Episode transformed = runEightwayD4Episode(symmetry);
      assertD4Actions(reference.actions,transformed.actions,9,symmetry);
      assertD4State(reference.placementState,transformed.placementState,symmetry);
      assertD4State(reference.finalState,transformed.finalState,symmetry);
      assertD4Settlement(reference.settlementResult,transformed.settlementResult,9,symmetry);

      int inverse = inverseSymmetry[symmetry];
      assertD4Actions(transformed.actions,reference.actions,9,inverse);
      assertD4State(transformed.placementState,reference.placementState,inverse);
      assertD4State(transformed.finalState,reference.finalState,inverse);
      assertD4Settlement(transformed.settlementResult,reference.settlementResult,9,inverse);
    }
  }

  // Captured-pending Eightway lifecycle and its no-op pop are also exact under D4 and inverse maps.
  {
    const int inverseSymmetry[8] = {0,1,2,3,4,6,5,7};
    ImmortalD4Episode reference = runCapturedEightwayD4Episode(0);
    testAssert(reference.placementState.getArmedEightwaySources().empty());
    testAssert(reference.placementState.getLedger().size() == 1);
    const CollapseGoLedgerEntry& captured = reference.placementState.getLedger().at(0);
    testAssert(captured.originKind == GameActionKind::EIGHTWAY);
    testAssert(captured.abilityState == CollapseGoLedgerAbilityState::INACTIVE);
    testAssert(captured.stoneState == CollapseGoLedgerStoneState::CAPTURED);
    testAssert(captured.settlementState == CollapseGoLedgerSettlementState::PENDING);
    testAssert(captured.tombstone);
    testAssert(reference.settlementResult.settlementSteps.size() == 1);
    testAssert(reference.settlementResult.settlementSteps[0].noOp);
    testAssert(!reference.settlementResult.settlementSteps[0].abilityDeactivated);
    testAssert(reference.settlementResult.settlementSteps[0].removalBatches.empty());

    for(int symmetry = 0; symmetry < 8; symmetry++) {
      ImmortalD4Episode transformed = runCapturedEightwayD4Episode(symmetry);
      assertD4Actions(reference.actions,transformed.actions,9,symmetry);
      assertD4State(reference.placementState,transformed.placementState,symmetry);
      assertD4State(reference.finalState,transformed.finalState,symmetry);
      assertD4Settlement(reference.settlementResult,transformed.settlementResult,9,symmetry);

      int inverse = inverseSymmetry[symmetry];
      assertD4Actions(transformed.actions,reference.actions,9,inverse);
      assertD4State(transformed.placementState,reference.placementState,inverse);
      assertD4State(transformed.finalState,reference.finalState,inverse);
      assertD4Settlement(transformed.settlementResult,reference.settlementResult,9,inverse);
    }
  }

  // Administrative pending-Double termination and its terminal event are exact under D4 and inverse maps.
  {
    const int inverseSymmetry[8] = {0,1,2,3,4,6,5,7};
    AdministrativeD4Episode reference = runAdministrativeD4Episode(0);
    testAssert(reference.pendingState.getPendingDouble().has_value());
    testAssert(reference.terminalState.getPendingDouble().has_value());
    testAssert(reference.terminationResult.terminalEvent.has_value());
    testAssert(reference.terminationResult.terminalEvent->reason ==
      CollapseGoTerminalReason::TIMEOUT);

    for(int symmetry = 0; symmetry < 8; symmetry++) {
      AdministrativeD4Episode transformed = runAdministrativeD4Episode(symmetry);
      assertD4Actions(reference.actions,transformed.actions,9,symmetry);
      assertD4State(reference.pendingState,transformed.pendingState,symmetry);
      assertD4State(reference.terminalState,transformed.terminalState,symmetry);
      assertD4Settlement(
        reference.terminationResult,transformed.terminationResult,9,symmetry
      );

      int inverse = inverseSymmetry[symmetry];
      assertD4Actions(transformed.actions,reference.actions,9,inverse);
      assertD4State(transformed.pendingState,reference.pendingState,inverse);
      assertD4State(transformed.terminalState,reference.terminalState,inverse);
      assertD4Settlement(
        transformed.terminationResult,reference.terminationResult,9,inverse
      );
    }
  }

  // An opponent may fill the last liberty without capturing a protected group.
  {
    CollapseGoState state(CollapseGoConfig::allOne(9));
    playNormal(state,8,8); playNormal(state,1,2);
    playNormal(state,8,7); playNormal(state,3,2);
    playNormal(state,7,8); playNormal(state,2,1);
    playImmortal(state,2,2);
    CollapseGoApplyResult fill = playNormal(state,2,3);
    testAssert(fill.capturedStones.empty());
    testAssert(state.getPosition().getColor(2,2) == C_BLACK);
    CollapseGoTopology topology = CollapseGoTopology::fullScanN4(
      state.getPosition(),state.getArmedImmortalAnchors()
    );
    const CollapseGoGroup& protectedGroup = topology.getGroupAt(2 + 2 * 9);
    testAssert(protectedGroup.liberties.empty());
    testAssert(protectedGroup.protectedByImmortal);
  }

  // A NORMAL stone may fill the last liberty and join an armed protected group.
  {
    CollapseGoState state(CollapseGoConfig::allOne(9));
    playProtectedAttachmentPrefix(state);
    playNormal(state,2,3);
    const CollapseGoStoneSource& attachedSource = state.getPosition().getCell(2,3).getSource();
    testAssert(attachedSource.originKind == GameActionKind::NORMAL);
    CollapseGoTopology topology = CollapseGoTopology::fullScanN4(
      state.getPosition(),state.getArmedImmortalAnchors()
    );
    const CollapseGoGroup& protectedGroup = topology.getGroupAt(2 + 2 * 9);
    testAssert(protectedGroup.stones == vector<int>({20,29}));
    testAssert(protectedGroup.liberties.empty());
    testAssert(protectedGroup.protectedByImmortal);
    state.checkConsistency();
  }

  // A Double start uses ordinary N4 mechanics and may likewise join a protected zero-liberty group.
  {
    CollapseGoState state(CollapseGoConfig::allOne(9));
    playProtectedAttachmentPrefix(state);
    playDoubleStart(state,2,3);
    testAssert(state.getPendingDouble().has_value());
    CollapseGoTopology topology = CollapseGoTopology::fullScanN4(
      state.getPosition(),state.getArmedImmortalAnchors()
    );
    const CollapseGoGroup& protectedGroup = topology.getGroupAt(2 + 2 * 9);
    testAssert(protectedGroup.liberties.empty());
    testAssert(protectedGroup.protectedByImmortal);
    testAssert(state.getPosition().getCell(2,3).getSource().originKind ==
      GameActionKind::DOUBLE_START);
    playPass(state);
    state.checkConsistency();
  }

  // A surviving Immortal becomes ordinary at settlement and may later be captured without lifecycle refund.
  {
    CollapseGoState state(CollapseGoConfig::allOne(9));
    playNormal(state,8,8); playNormal(state,1,0);
    playNormal(state,8,7); playNormal(state,0,1);
    playNormal(state,7,8); playNormal(state,2,1);
    playImmortal(state,1,1);
    playPass(state);
    CollapseGoApplyResult settlement = playPass(state);
    testAssert(settlement.settlementSteps.size() == 1);
    testAssert(settlement.settlementSteps[0].abilityDeactivated);
    testAssert(settlement.settlementSteps[0].removalBatches.empty());
    testAssert(state.getPosition().getColor(1,1) == C_BLACK);
    testAssert(state.getLedger().at(0).abilityState == CollapseGoLedgerAbilityState::INACTIVE);
    testAssert(state.getLedger().at(0).stoneState == CollapseGoLedgerStoneState::ON_BOARD);
    testAssert(state.getLedger().at(0).tombstone);

    CollapseGoApplyResult capture = playNormal(state,1,2);
    testAssert(capture.capturedStones == vector<Loc>({Location::getLoc(1,1,9)}));
    testAssert(state.getPosition().isEmpty(1,1));
    testAssert(state.getLedger().at(0).abilityState == CollapseGoLedgerAbilityState::INACTIVE);
    testAssert(state.getLedger().at(0).stoneState == CollapseGoLedgerStoneState::CAPTURED);
    testAssert(state.getLedger().at(0).settlementState == CollapseGoLedgerSettlementState::SETTLED);
    testAssert(state.getLedger().at(0).tombstone);
    testAssert(state.getUsedQuota(P_BLACK,CollapseGoAbility::IMMORTAL) == 1);
    testAssert(state.getExpiredQuota(P_BLACK,CollapseGoAbility::IMMORTAL) == 0);
    state.checkConsistency();
  }

  // A live Eightway may be captured before settlement; its retained event later pops as a no-op.
  {
    CollapseGoConfig config(9,CollapseGoQuotas(0,0,1),CollapseGoQuotas());
    CollapseGoState state(config);
    playEightway(state,4,4);
    const pair<int,int> ring[8] = {
      {3,3},{4,3},{5,3},{3,4},{5,4},{3,5},{4,5},{5,5},
    };
    for(int i = 0; i < 8; i++) {
      CollapseGoApplyResult whiteMove = playNormal(state,ring[i].first,ring[i].second);
      if(i == 7) {
        testAssert(whiteMove.capturedStones == vector<Loc>({Location::getLoc(4,4,9)}));
      }
      else
        playNormal(state,i,8);
    }

    testAssert(state.getPosition().isEmpty(4,4));
    testAssert(state.getArmedEightwaySources().empty());
    const CollapseGoLedgerEntry& captured = state.getLedger().at(0);
    testAssert(captured.originKind == GameActionKind::EIGHTWAY);
    testAssert(captured.abilityState == CollapseGoLedgerAbilityState::INACTIVE);
    testAssert(captured.stoneState == CollapseGoLedgerStoneState::CAPTURED);
    testAssert(captured.settlementState == CollapseGoLedgerSettlementState::PENDING);
    testAssert(captured.tombstone);
    testAssert(state.getUsedQuota(P_BLACK,CollapseGoAbility::EIGHTWAY) == 1);

    playPass(state);
    CollapseGoApplyResult trigger = playPass(state);
    testAssert(trigger.settlementTriggered);
    testAssert(trigger.settlementSteps.size() == 1);
    const CollapseGoSettlementStep& step = trigger.settlementSteps[0];
    testAssert(step.originKind == GameActionKind::EIGHTWAY);
    testAssert(step.noOp);
    testAssert(!step.abilityDeactivated);
    testAssert(step.removalBatches.empty());
    testAssert(step.stableOccupancy == state.getPositionalSuperkoHistory().at(18).getOccupancy());
    testAssert(step.positionalSuperkoHistoryIndex == 19);
    testAssert(state.getLedger().at(0).settlementState == CollapseGoLedgerSettlementState::SETTLED);
    testAssert(state.getAtomicActionCount() == 18);
    testAssert(state.getLogPosition() == 19);
    testAssert(state.getPositionalSuperkoHistory().size() == 20);
    state.checkConsistency();
  }

  // A PSK rejection after tentative Eightway capture rolls back the source lifecycle and full state.
  {
    CollapseGoConfig config(9,CollapseGoQuotas(0,0,1),CollapseGoQuotas());
    CollapseGoState state(config);
    playEightway(state,4,4);
    const pair<int,int> ring[8] = {
      {3,3},{4,3},{5,3},{3,4},{5,4},{3,5},{4,5},{5,5},
    };
    for(int index = 0; index < 7; index++) {
      playNormal(state,ring[index].first,ring[index].second);
      playNormal(state,index,8);
    }
    testAssert(state.getActor() == P_WHITE);
    testAssert(state.getArmedEightwaySources() == vector<int>({40}));

    CollapseGoState acceptedCapture(state);
    CollapseGoApplyResult accepted = playNormal(
      acceptedCapture,ring[7].first,ring[7].second
    );
    testAssert(accepted.capturedStones == vector<Loc>({Location::getLoc(4,4,9)}));
    CollapseGoStateTestAccess::replacePskOccupancy(
      state,2,acceptedCapture.getPosition().getRowMajorOccupancy()
    );
    state.checkConsistency();

    expectRejectedAtomically(
      state,P_WHITE,normalAction(9,ring[7].first,ring[7].second),
      CollapseGoApplyError::POSITIONAL_SUPERKO,true
    );
    const CollapseGoLedgerEntry& retained = state.getLedger().at(0);
    testAssert(retained.abilityState == CollapseGoLedgerAbilityState::ARMED);
    testAssert(retained.stoneState == CollapseGoLedgerStoneState::ON_BOARD);
    testAssert(retained.settlementState == CollapseGoLedgerSettlementState::PENDING);
    testAssert(!retained.tombstone);
    testAssert(state.getPosition().getColor(4,4) == C_BLACK);
    testAssert(state.getArmedEightwaySources() == vector<int>({40}));
  }

  // Popping a newer Immortal may capture an older Eightway source, making the older pop a no-op.
  {
    CollapseGoConfig config(9,CollapseGoQuotas(1,0,1),CollapseGoQuotas());
    CollapseGoState state(config);
    playEightway(state,4,4);
    const pair<int,int> surround[8] = {
      {3,3},{4,3},{5,3},{3,4},{5,4},{3,5},{5,5},{4,6},
    };
    for(int i = 0; i < 8; i++) {
      playNormal(state,surround[i].first,surround[i].second);
      if(i < 7)
        playNormal(state,i,8);
    }
    testAssert(state.getArmedEightwaySources() == vector<int>({40}));
    CollapseGoApplyResult immortalPlacement = playImmortal(state,4,5);
    testAssert(immortalPlacement.capturedStones.empty());
    CollapseGoTopology protectedTopology = CollapseGoTopology::fullScan(
      state.getPosition(),state.getArmedImmortalAnchors(),state.getArmedEightwaySources()
    );
    testAssert(protectedTopology.getGroupAt(40).stones == vector<int>({40,49}));
    testAssert(protectedTopology.getGroupAt(40).liberties.empty());
    testAssert(protectedTopology.getGroupAt(40).protectedByImmortal);

    playPass(state);
    CollapseGoApplyResult trigger = playPass(state);
    testAssert(trigger.settlementSteps.size() == 2);
    const CollapseGoSettlementStep& newer = trigger.settlementSteps[0];
    testAssert(newer.originActionNumber == 17);
    testAssert(newer.originKind == GameActionKind::IMMORTAL);
    testAssert(newer.abilityDeactivated && !newer.noOp);
    testAssert(newer.removalBatches.size() == 1);
    testAssert(newer.removalBatches[0].blackStones == vector<Loc>({
      Location::getLoc(4,4,9),Location::getLoc(4,5,9)
    }));
    testAssert(newer.removalBatches[0].whiteStones.empty());
    const CollapseGoSettlementStep& older = trigger.settlementSteps[1];
    testAssert(older.originActionNumber == 1);
    testAssert(older.originKind == GameActionKind::EIGHTWAY);
    testAssert(older.noOp);
    testAssert(!older.abilityDeactivated);
    testAssert(older.removalBatches.empty());
    testAssert(older.stableOccupancy == newer.stableOccupancy);
    testAssert(state.getPosition().isEmpty(4,4));
    testAssert(state.getPosition().isEmpty(4,5));
    for(size_t index = 0; index < state.getLedger().size(); index++) {
      testAssert(state.getLedger().at(index).abilityState == CollapseGoLedgerAbilityState::INACTIVE);
      testAssert(state.getLedger().at(index).stoneState == CollapseGoLedgerStoneState::CAPTURED);
      testAssert(state.getLedger().at(index).settlementState == CollapseGoLedgerSettlementState::SETTLED);
      testAssert(state.getLedger().at(index).tombstone);
    }
    testAssert(trigger.positionalSuperkoAppends == 3);
    state.checkConsistency();
  }

  // SYNTHETIC invariant-shell coverage: closure selects both colors from one rebuild and one batch.
  // This begins from a valid reachable state, then test access deliberately fabricates an otherwise
  // invalid pre-settlement white zero-liberty group. It is not claimed as reachable gameplay.
  {
    CollapseGoState state(CollapseGoConfig::allOne(19));
    playImmortalTrueEyePrefix(state);
    playImmortal(state,9,9);
    state.checkConsistency();
    testAssert(state.getAtomicActionCount() == 17);
    testAssert(state.getActor() == P_WHITE);
    testAssert(state.getArmedImmortalAnchors() == vector<int>({180}));

    CollapseGoStateTestAccess::appendSyntheticNormalStone(state,4,4,P_WHITE);
    CollapseGoStateTestAccess::appendSyntheticNormalStone(state,4,3,P_BLACK);
    CollapseGoStateTestAccess::appendSyntheticNormalStone(state,3,4,P_BLACK);
    CollapseGoStateTestAccess::appendSyntheticNormalStone(state,5,4,P_BLACK);
    CollapseGoStateTestAccess::appendSyntheticNormalStone(state,4,5,P_BLACK);
    CollapseGoStateTestAccess::appendSyntheticPass(state);
    CollapseGoStateTestAccess::appendSyntheticPass(state);
    testAssert(state.getAtomicActionCount() == 24);
    testAssert(state.getLogPosition() == 24);
    testAssert(state.getPositionalSuperkoHistory().size() == 25);
    expectStringError([&]() { state.checkConsistency(); });

    CollapseGoApplyResult settlement = CollapseGoReducerTestAccess::completeSyntheticSettlement(
      state,CollapseGoSettlementReason::PRE_THRESHOLD_TWO_PASSES
    );
    testAssert(settlement.accepted);
    testAssert(settlement.settlementTriggered);
    testAssert(settlement.settlementReason == CollapseGoSettlementReason::PRE_THRESHOLD_TWO_PASSES);
    testAssert(settlement.positionalSuperkoAppends == 1);
    testAssert(settlement.settlementSteps.size() == 1);
    const CollapseGoSettlementStep& step = settlement.settlementSteps[0];
    testAssert(step.originActionNumber == 17);
    testAssert(step.originKind == GameActionKind::IMMORTAL);
    testAssert(step.abilityDeactivated && !step.noOp);
    testAssert(step.removalBatches.size() == 1);
    testAssert(step.removalBatches[0].blackStones ==
      vector<Loc>({Location::getLoc(9,9,19)}));
    testAssert(step.removalBatches[0].whiteStones ==
      vector<Loc>({Location::getLoc(4,4,19)}));
    testAssert(step.positionalSuperkoHistoryIndex == 25);
    testAssert(step.stableOccupancy == state.getPosition().getRowMajorOccupancy());
    testAssert(state.getPosition().isEmpty(9,9));
    testAssert(state.getPosition().isEmpty(4,4));

    const CollapseGoLedgerEntry& capturedSource = state.getLedger().at(0);
    testAssert(capturedSource.abilityState == CollapseGoLedgerAbilityState::INACTIVE);
    testAssert(capturedSource.stoneState == CollapseGoLedgerStoneState::CAPTURED);
    testAssert(capturedSource.settlementState == CollapseGoLedgerSettlementState::SETTLED);
    testAssert(capturedSource.tombstone);
    testAssert(state.getSettledLedgerCount() == 1);
    testAssert(state.getAtomicActionCount() == 24);
    testAssert(state.getLogPosition() == 25);
    testAssert(state.getPositionalSuperkoHistory().size() == 26);
    testAssert(state.getPositionalSuperkoHistory().back() == PositionalSuperkoKey(
      19,state.getPosition().getRowMajorOccupancy()
    ));
    testAssert(state.getPhase() == CollapseGoPhase::ORDINARY_PLAY);
    testAssert(state.getActor() == P_WHITE);
    state.checkConsistency();
  }

  // Action T commits a zero-liberty Immortal snapshot before its first settlement pop removes it.
  {
    CollapseGoState state(CollapseGoConfig::allOne(9));
    playThresholdTrueEyePrefix(state);
    const int anchor = 4 + 4 * 9;
    testAssert(state.getAtomicActionCount() == 33);
    testAssert(state.getActor() == P_WHITE);
    testAssert(state.getPosition().isEmpty(anchor));

    CollapseGoApplyResult trigger = playImmortal(state,4,4);
    testAssert(trigger.settlementTriggered);
    testAssert(trigger.settlementReason == CollapseGoSettlementReason::THRESHOLD);
    testAssert(trigger.positionalSuperkoAppends == 2);
    testAssert(trigger.capturedStones.empty());
    testAssert(trigger.settlementSteps.size() == 1);
    const CollapseGoSettlementStep& step = trigger.settlementSteps[0];
    testAssert(step.originActionNumber == 34);
    testAssert(step.originKind == GameActionKind::IMMORTAL);
    testAssert(step.sourcePoint == anchor);
    testAssert(step.abilityDeactivated);
    testAssert(!step.noOp);
    testAssert(step.removalBatches.size() == 1);
    testAssert(step.removalBatches[0].blackStones.empty());
    testAssert(step.removalBatches[0].whiteStones == vector<Loc>({Location::getLoc(4,4,9)}));
    testAssert(step.positionalSuperkoHistoryIndex == 35);

    const vector<uint8_t>& actionOccupancy =
      state.getPositionalSuperkoHistory().at(34).getOccupancy();
    const vector<uint8_t>& settlementOccupancy =
      state.getPositionalSuperkoHistory().at(35).getOccupancy();
    testAssert(actionOccupancy[static_cast<size_t>(anchor)] == static_cast<uint8_t>(C_WHITE));
    testAssert(settlementOccupancy[static_cast<size_t>(anchor)] == static_cast<uint8_t>(C_EMPTY));
    testAssert(actionOccupancy != settlementOccupancy);
    testAssert(step.stableOccupancy == settlementOccupancy);
    testAssert(state.getPosition().isEmpty(anchor));

    const CollapseGoLedgerEntry& settled = state.getLedger().at(0);
    testAssert(settled.sourcePoint == anchor);
    testAssert(settled.abilityState == CollapseGoLedgerAbilityState::INACTIVE);
    testAssert(settled.stoneState == CollapseGoLedgerStoneState::CAPTURED);
    testAssert(settled.settlementState == CollapseGoLedgerSettlementState::SETTLED);
    testAssert(settled.tombstone);
    testAssert(state.getActor() == P_BLACK);
    testAssert(state.getPhase() == CollapseGoPhase::ORDINARY_PLAY);
    testAssert(state.getAtomicActionCount() == 34);
    testAssert(state.getRevision() == 34);
    testAssert(state.getLogPosition() == 35);
    testAssert(state.getSettledLedgerCount() == 1);
    testAssert(state.getPositionalSuperkoHistory().size() == 36);
    state.checkConsistency();
  }

  // Action T arms Eightway for placement, commits its N8 snapshot, then pops it first to N4.
  {
    CollapseGoState state(CollapseGoConfig::allOne(9));
    playThresholdTrueEyePrefix(state);
    const int sourcePoint = 4 + 4 * 9;
    testAssert(state.getAtomicActionCount() == 33);
    testAssert(state.getActor() == P_WHITE);

    CollapseGoApplyResult trigger = playEightway(state,4,4);
    testAssert(trigger.settlementTriggered);
    testAssert(trigger.settlementReason == CollapseGoSettlementReason::THRESHOLD);
    testAssert(trigger.capturedStones.empty());
    testAssert(trigger.atomicStateSnapshot.has_value());
    const CollapseGoState& atomic = trigger.atomicStateSnapshot.value();
    testAssert(atomic.getAtomicActionCount() == 34);
    testAssert(atomic.getRevision() == 34);
    testAssert(atomic.getLogPosition() == 34);
    testAssert(atomic.getPhase() == CollapseGoPhase::COLLAPSE_PLAY);
    testAssert(atomic.getActor() == P_BLACK);
    testAssert(atomic.getPosition().getColor(sourcePoint) == C_WHITE);
    testAssert(atomic.getArmedEightwaySources() == vector<int>({sourcePoint}));
    testAssert(atomic.getLedger().size() == 1);
    const CollapseGoLedgerEntry& atomicEntry = atomic.getLedger().at(0);
    testAssert(atomicEntry.abilityState == CollapseGoLedgerAbilityState::ARMED);
    testAssert(atomicEntry.stoneState == CollapseGoLedgerStoneState::ON_BOARD);
    testAssert(atomicEntry.settlementState == CollapseGoLedgerSettlementState::PENDING);
    testAssert(!atomicEntry.tombstone);
    testAssert(atomic.getPositionalSuperkoHistory().size() == 35);
    testAssert(trigger.positionalSuperkoAppends == 2);
    testAssert(trigger.settlementSteps.size() == 1);
    const CollapseGoSettlementStep& step = trigger.settlementSteps[0];
    testAssert(step.originActionNumber == 34);
    testAssert(step.originKind == GameActionKind::EIGHTWAY);
    testAssert(step.sourcePoint == sourcePoint);
    testAssert(step.abilityDeactivated && !step.noOp);
    testAssert(step.removalBatches.size() == 1);
    testAssert(step.removalBatches[0].blackStones.empty());
    testAssert(step.removalBatches[0].whiteStones ==
      vector<Loc>({Location::getLoc(4,4,9)}));
    testAssert(step.positionalSuperkoHistoryIndex == 35);

    const vector<uint8_t>& actionOccupancy =
      state.getPositionalSuperkoHistory().at(34).getOccupancy();
    const vector<uint8_t>& settlementOccupancy =
      state.getPositionalSuperkoHistory().at(35).getOccupancy();
    testAssert(actionOccupancy[static_cast<size_t>(sourcePoint)] == static_cast<uint8_t>(C_WHITE));
    testAssert(settlementOccupancy[static_cast<size_t>(sourcePoint)] == static_cast<uint8_t>(C_EMPTY));
    testAssert(actionOccupancy != settlementOccupancy);
    testAssert(step.stableOccupancy == settlementOccupancy);

    const CollapseGoLedgerEntry& settled = state.getLedger().at(0);
    testAssert(settled.originKind == GameActionKind::EIGHTWAY);
    testAssert(settled.abilityState == CollapseGoLedgerAbilityState::INACTIVE);
    testAssert(settled.stoneState == CollapseGoLedgerStoneState::CAPTURED);
    testAssert(settled.settlementState == CollapseGoLedgerSettlementState::SETTLED);
    testAssert(settled.tombstone);
    testAssert(state.getUsedQuota(P_WHITE,CollapseGoAbility::EIGHTWAY) == 1);
    testAssert(state.getExpiredQuota(P_WHITE,CollapseGoAbility::EIGHTWAY) == 0);
    testAssert(state.getActor() == P_BLACK);
    testAssert(state.getPhase() == CollapseGoPhase::ORDINARY_PLAY);
    state.checkConsistency();
  }

  // With two anchors in one zero-liberty group, the newest pop leaves protection and the older pop removes both.
  {
    CollapseGoConfig config(9,CollapseGoQuotas(2,0,0),CollapseGoQuotas(0,0,0));
    CollapseGoState state(config);
    playImmortal(state,2,2); playNormal(state,2,1);
    playNormal(state,8,8); playNormal(state,1,2);
    playNormal(state,8,7); playNormal(state,3,2);
    playNormal(state,7,8); playNormal(state,1,3);
    playNormal(state,7,7); playNormal(state,3,3);
    playNormal(state,6,8); playNormal(state,2,4);
    playImmortal(state,2,3);
    CollapseGoTopology before = CollapseGoTopology::fullScanN4(
      state.getPosition(),state.getArmedImmortalAnchors()
    );
    testAssert(before.getGroupAt(20).liberties.empty());
    testAssert(before.getGroupAt(20).protectedByImmortal);
    testAssert(state.getArmedImmortalAnchors() == vector<int>({20,29}));

    playPass(state);
    CollapseGoApplyResult trigger = playPass(state);
    testAssert(trigger.settlementTriggered);
    testAssert(trigger.settlementReason == CollapseGoSettlementReason::PRE_THRESHOLD_TWO_PASSES);
    testAssert(trigger.positionalSuperkoAppends == 3);
    testAssert(trigger.settlementSteps.size() == 2);
    const CollapseGoSettlementStep& newest = trigger.settlementSteps[0];
    testAssert(newest.originActionNumber == 13);
    testAssert(newest.abilityDeactivated && !newest.noOp);
    testAssert(newest.removalBatches.empty());
    testAssert(newest.positionalSuperkoHistoryIndex == 16);
    testAssert(newest.stableOccupancy == state.getPositionalSuperkoHistory().at(16).getOccupancy());
    testAssert(newest.stableOccupancy[20] == static_cast<uint8_t>(C_BLACK));
    testAssert(newest.stableOccupancy[29] == static_cast<uint8_t>(C_BLACK));
    const CollapseGoSettlementStep& oldest = trigger.settlementSteps[1];
    testAssert(oldest.originActionNumber == 1);
    testAssert(oldest.abilityDeactivated && !oldest.noOp);
    testAssert(oldest.removalBatches.size() == 1);
    testAssert(oldest.removalBatches[0].blackStones == vector<Loc>({
      Location::getLoc(2,2,9),Location::getLoc(2,3,9)
    }));
    testAssert(oldest.removalBatches[0].whiteStones.empty());
    testAssert(oldest.positionalSuperkoHistoryIndex == 17);
    testAssert(oldest.stableOccupancy == state.getPositionalSuperkoHistory().at(17).getOccupancy());
    testAssert(state.getPosition().isEmpty(2,2));
    testAssert(state.getPosition().isEmpty(2,3));
    for(size_t i = 0; i < state.getLedger().size(); i++) {
      testAssert(state.getLedger().at(i).abilityState == CollapseGoLedgerAbilityState::INACTIVE);
      testAssert(state.getLedger().at(i).stoneState == CollapseGoLedgerStoneState::CAPTURED);
      testAssert(state.getLedger().at(i).settlementState == CollapseGoLedgerSettlementState::SETTLED);
      testAssert(state.getLedger().at(i).tombstone);
    }
    testAssert(state.getAtomicActionCount() == 15);
    testAssert(state.getRevision() == 15);
    testAssert(state.getLogPosition() == 17);
    testAssert(state.getSettledLedgerCount() == 2);
    testAssert(state.getPositionalSuperkoHistory().size() == 18);
    testAssert(state.getPhase() == CollapseGoPhase::ORDINARY_PLAY);
    testAssert(state.getActor() == P_WHITE);
    state.checkConsistency();
  }

  // Mixed Double and Immortal entries settle in one global newest-to-oldest order.
  {
    CollapseGoState state(CollapseGoConfig::allOne(9));
    playImmortal(state,0,0);
    playDoubleStart(state,8,8);
    playNormal(state,8,7);
    playDoubleStart(state,1,0);
    playPass(state);
    playImmortal(state,7,8);
    playPass(state);
    CollapseGoApplyResult trigger = playPass(state);
    testAssert(trigger.settlementTriggered);
    testAssert(trigger.settlementReason == CollapseGoSettlementReason::PRE_THRESHOLD_TWO_PASSES);
    testAssert(trigger.settlementSteps.size() == 4);
    const int64_t expectedOrigins[4] = {6,4,2,1};
    const GameActionKind expectedKinds[4] = {
      GameActionKind::IMMORTAL,
      GameActionKind::DOUBLE_START,
      GameActionKind::DOUBLE_START,
      GameActionKind::IMMORTAL,
    };
    const bool expectedDeactivated[4] = {true,false,false,true};
    for(size_t i = 0; i < trigger.settlementSteps.size(); i++) {
      const CollapseGoSettlementStep& step = trigger.settlementSteps[i];
      testAssert(step.stepIndex == static_cast<int64_t>(i));
      testAssert(step.originActionNumber == expectedOrigins[i]);
      testAssert(step.originKind == expectedKinds[i]);
      testAssert(step.abilityDeactivated == expectedDeactivated[i]);
      testAssert(step.noOp != expectedDeactivated[i]);
      testAssert(step.removalBatches.empty());
      testAssert(step.positionalSuperkoHistoryIndex == static_cast<int64_t>(9 + i));
      testAssert(step.stableOccupancy ==
        state.getPositionalSuperkoHistory().at(static_cast<size_t>(9 + i)).getOccupancy());
    }
    testAssert(trigger.positionalSuperkoAppends == 5);
    testAssert(state.getAtomicActionCount() == 8);
    testAssert(state.getRevision() == 8);
    testAssert(state.getLogPosition() == 12);
    testAssert(state.getSettledLedgerCount() == 4);
    testAssert(state.getPositionalSuperkoHistory().size() == 13);
    testAssert(state.getActor() == P_BLACK);
    testAssert(state.getPhase() == CollapseGoPhase::ORDINARY_PLAY);
    state.checkConsistency();
  }

  // Double, Immortal, and Eightway from both players share one global newest-to-oldest queue.
  {
    CollapseGoState state(CollapseGoConfig::allOne(9));
    playEightway(state,0,0);
    playImmortal(state,8,8);
    playDoubleStart(state,1,0);
    playNormal(state,2,0);
    playEightway(state,7,8);
    playPass(state);
    CollapseGoApplyResult trigger = playPass(state);

    testAssert(trigger.settlementTriggered);
    testAssert(trigger.settlementSteps.size() == 4);
    const int64_t expectedOrigins[4] = {5,3,2,1};
    const Player expectedOwners[4] = {P_WHITE,P_BLACK,P_WHITE,P_BLACK};
    const GameActionKind expectedKinds[4] = {
      GameActionKind::EIGHTWAY,
      GameActionKind::DOUBLE_START,
      GameActionKind::IMMORTAL,
      GameActionKind::EIGHTWAY,
    };
    const bool expectedDeactivated[4] = {true,false,true,true};
    for(size_t index = 0; index < trigger.settlementSteps.size(); index++) {
      const CollapseGoSettlementStep& step = trigger.settlementSteps[index];
      testAssert(step.stepIndex == static_cast<int64_t>(index));
      testAssert(step.originActionNumber == expectedOrigins[index]);
      testAssert(step.owner == expectedOwners[index]);
      testAssert(step.originKind == expectedKinds[index]);
      testAssert(step.abilityDeactivated == expectedDeactivated[index]);
      testAssert(step.noOp != expectedDeactivated[index]);
      testAssert(step.removalBatches.empty());
      testAssert(step.positionalSuperkoHistoryIndex == static_cast<int64_t>(8 + index));
    }
    testAssert(trigger.positionalSuperkoAppends == 5);
    testAssert(state.getAtomicActionCount() == 7);
    testAssert(state.getLogPosition() == 11);
    testAssert(state.getPositionalSuperkoHistory().size() == 12);
    testAssert(state.getActor() == P_BLACK);
    testAssert(state.getPhase() == CollapseGoPhase::ORDINARY_PLAY);
    testAssert(state.getArmedImmortalAnchors().empty());
    testAssert(state.getArmedEightwaySources().empty());
    testAssert(state.getUsedQuota(P_BLACK,CollapseGoAbility::EIGHTWAY) == 1);
    testAssert(state.getUsedQuota(P_WHITE,CollapseGoAbility::EIGHTWAY) == 1);
    state.checkConsistency();
  }

  // Malformed restored shells cannot forge live Immortal or Eightway source lifecycles.
  {
    CollapseGoState tombstone(CollapseGoConfig::allOne(9));
    playImmortal(tombstone,4,4);
    CollapseGoStateTestAccess::ledgerEntry(tombstone,0).tombstone = true;
    expectStringError([&]() { tombstone.checkConsistency(); });

    CollapseGoState captured(CollapseGoConfig::allOne(9));
    playImmortal(captured,4,4);
    CollapseGoStateTestAccess::ledgerEntry(captured,0).stoneState =
      CollapseGoLedgerStoneState::CAPTURED;
    expectStringError([&]() { captured.checkConsistency(); });

    CollapseGoState capturedPending(CollapseGoConfig::allOne(9));
    playImmortal(capturedPending,4,4);
    CollapseGoLedgerEntry& capturedPendingEntry =
      CollapseGoStateTestAccess::ledgerEntry(capturedPending,0);
    capturedPendingEntry.abilityState = CollapseGoLedgerAbilityState::INACTIVE;
    capturedPendingEntry.stoneState = CollapseGoLedgerStoneState::CAPTURED;
    capturedPendingEntry.tombstone = true;
    expectStringError([&]() { capturedPending.checkConsistency(); });

    CollapseGoState missingAnchor(CollapseGoConfig::allOne(9));
    playImmortal(missingAnchor,4,4);
    CollapseGoStateTestAccess::ledgerEntry(missingAnchor,0).sourcePoint = 0;
    expectStringError([&]() { missingAnchor.checkConsistency(); });

    CollapseGoState eightwayTombstone(CollapseGoConfig::allOne(9));
    playEightway(eightwayTombstone,4,4);
    CollapseGoStateTestAccess::ledgerEntry(eightwayTombstone,0).tombstone = true;
    expectStringError([&]() { eightwayTombstone.checkConsistency(); });

    CollapseGoState eightwayCapturedMarker(CollapseGoConfig::allOne(9));
    playEightway(eightwayCapturedMarker,4,4);
    CollapseGoStateTestAccess::ledgerEntry(eightwayCapturedMarker,0).stoneState =
      CollapseGoLedgerStoneState::CAPTURED;
    expectStringError([&]() { eightwayCapturedMarker.checkConsistency(); });

    CollapseGoState eightwayInactiveOnBoard(CollapseGoConfig::allOne(9));
    playEightway(eightwayInactiveOnBoard,4,4);
    CollapseGoLedgerEntry& inactiveEntry =
      CollapseGoStateTestAccess::ledgerEntry(eightwayInactiveOnBoard,0);
    inactiveEntry.abilityState = CollapseGoLedgerAbilityState::INACTIVE;
    inactiveEntry.stoneState = CollapseGoLedgerStoneState::CAPTURED;
    inactiveEntry.tombstone = true;
    expectStringError([&]() { eightwayInactiveOnBoard.checkConsistency(); });

    CollapseGoState missingEightwaySource(CollapseGoConfig::allOne(9));
    playEightway(missingEightwaySource,4,4);
    CollapseGoStateTestAccess::ledgerEntry(missingEightwaySource,0).sourcePoint = 0;
    expectStringError([&]() { missingEightwaySource.checkConsistency(); });

    CollapseGoState missingEightwayHistory(CollapseGoConfig::allOne(9));
    playEightway(missingEightwayHistory,4,4);
    vector<uint8_t> alteredEightwayStart =
      missingEightwayHistory.getPositionalSuperkoHistory().at(1).getOccupancy();
    alteredEightwayStart[40] = static_cast<uint8_t>(C_EMPTY);
    CollapseGoStateTestAccess::replacePskOccupancy(
      missingEightwayHistory,1,alteredEightwayStart
    );
    expectStringError([&]() { missingEightwayHistory.checkConsistency(); });
  }

  // Both administrative reasons and both losers commit one typed terminal event at collapse boundaries.
  {
    const pair<CollapseGoAdministrativeTerminationReason,CollapseGoTerminalReason> reasons[] = {
      {CollapseGoAdministrativeTerminationReason::RESIGNATION,CollapseGoTerminalReason::RESIGNATION},
      {CollapseGoAdministrativeTerminationReason::TIMEOUT,CollapseGoTerminalReason::TIMEOUT},
    };
    for(const auto& reason: reasons) {
      for(Player loser: {P_BLACK,P_WHITE}) {
        CollapseGoState state(CollapseGoConfig::allOne(9));
        CollapseGoState before(state);
        const bool loserIsCurrentActor = loser == before.getActor();
        CollapseGoApplyResult result = terminateAccepted(state,loser,reason.first);

        testAssert(result.accepted);
        testAssert(result.error == CollapseGoApplyError::NONE);
        testAssert(result.capturedStones.empty());
        testAssert(!result.atomicStateSnapshot.has_value());
        testAssert(result.settlementSteps.empty());
        testAssert(!result.settlementTriggered);
        testAssert(result.settlementReason == CollapseGoSettlementReason::NONE);
        testAssert(result.terminalEvent.has_value());
        testAssert(!result.terminalScoreEventEmitted);
        testAssert(result.positionalSuperkoAppends == 1);

        testAssert(state.getPhase() == CollapseGoPhase::TERMINAL);
        testAssert(state.getActor() == C_EMPTY);
        testAssert(state.getAtomicActionCount() == 0);
        testAssert(state.getConsecutivePasses() == 0);
        testAssert(!state.isSettlementCompleted());
        testAssert(state.getRevision() == 1);
        testAssert(state.getLogPosition() == 1);
        testAssert(state.getSettledLedgerCount() == 0);
        testAssert(state.getStableTerminalEventCount() == 1);
        testAssert(state.getScore() == CollapseGoScore());
        testAssert(state.getTerminalState().has_value());
        const CollapseGoTerminalState& terminal = *state.getTerminalState();
        testAssert(terminal.reason == reason.second);
        testAssert(terminal.winner == getOpp(loser));
        testAssert(terminal.loser == loser);
        testAssert((terminal.loser == before.getActor()) == loserIsCurrentActor);

        const CollapseGoTerminalEvent& event = *result.terminalEvent;
        testAssert(event.reason == terminal.reason);
        testAssert(event.winner == terminal.winner);
        testAssert(event.loser == terminal.loser);
        testAssert(event.score == CollapseGoScore());
        testAssert(!event.settlementCompleted);
        testAssert(event.stablePosition.isEqualForTesting(before.getPosition()));
        testAssert(event.stableOccupancy == before.getPosition().getRowMajorOccupancy());
        testAssert(event.positionalSuperkoHistoryIndex == 1);
        testAssert(event.revision == 1);
        testAssert(event.logPosition == 1);
        CollapseGoTerminalEvent copiedEvent(event);
        testAssert(copiedEvent == event);
        testAssert(!(copiedEvent != event));

        testAssert(state.getPosition().isEqualForTesting(before.getPosition()));
        testAssert(state.getLedger() == before.getLedger());
        testAssert(state.getPendingDouble() == before.getPendingDouble());
        for(Player player: {P_BLACK,P_WHITE}) {
          for(CollapseGoAbility ability: {
            CollapseGoAbility::IMMORTAL,
            CollapseGoAbility::DOUBLE_MOVE,
            CollapseGoAbility::EIGHTWAY,
          }) {
            testAssert(state.getInitialQuota(player,ability) == before.getInitialQuota(player,ability));
            testAssert(state.getRemainingQuota(player,ability) == before.getRemainingQuota(player,ability));
            testAssert(state.getUsedQuota(player,ability) == before.getUsedQuota(player,ability));
            testAssert(state.getExpiredQuota(player,ability) == before.getExpiredQuota(player,ability));
          }
        }
        testAssert(state.getPositionalSuperkoHistory().size() == 2);
        testAssert(state.getPositionalSuperkoHistory().at(0) ==
          before.getPositionalSuperkoHistory().at(0));
        testAssert(state.getPositionalSuperkoHistory().at(1) ==
          before.getPositionalSuperkoHistory().at(0));
        testAssert(CollapseGoReducer::deriveLegalMask(state).none());
        state.checkConsistency();

        expectRejectedAtomically(
          state,P_BLACK,normalAction(9,4,4),CollapseGoApplyError::TERMINAL_STATE,true
        );
        expectTerminationRejectedAtomically(
          state,loser,reason.first,CollapseGoApplyError::TERMINAL_STATE
        );
      }
    }
  }

  // Otherwise-identical administrative reasons remain distinct in state, result, and event equality.
  {
    CollapseGoState resignationState(CollapseGoConfig::allOne(9));
    CollapseGoState timeoutState(resignationState);
    CollapseGoApplyResult resignationResult = terminateAccepted(
      resignationState,P_BLACK,CollapseGoAdministrativeTerminationReason::RESIGNATION
    );
    CollapseGoApplyResult timeoutResult = terminateAccepted(
      timeoutState,P_BLACK,CollapseGoAdministrativeTerminationReason::TIMEOUT
    );

    testAssert(resignationState.getTerminalState().has_value());
    testAssert(timeoutState.getTerminalState().has_value());
    testAssert(*resignationState.getTerminalState() != *timeoutState.getTerminalState());
    testAssert(!resignationState.isEqualForTesting(timeoutState));
    testAssert(resignationResult.terminalEvent.has_value());
    testAssert(timeoutResult.terminalEvent.has_value());
    testAssert(*resignationResult.terminalEvent != *timeoutResult.terminalEvent);
    testAssert(!applyResultsEqualForTesting(resignationResult,timeoutResult));

    CollapseGoState normalizedTimeoutState(timeoutState);
    CollapseGoStateTestAccess::terminalState(normalizedTimeoutState).reason =
      CollapseGoTerminalReason::RESIGNATION;
    testAssert(resignationState.isEqualForTesting(normalizedTimeoutState));
    CollapseGoApplyResult normalizedTimeoutResult(timeoutResult);
    normalizedTimeoutResult.terminalEvent->reason = CollapseGoTerminalReason::RESIGNATION;
    assertExactApplyResult(resignationResult,normalizedTimeoutResult);
  }

  // Source-aware terminal snapshots distinguish otherwise matching occupancy and counters.
  {
    CollapseGoState normalState(CollapseGoConfig::allOne(9));
    CollapseGoState doubleState(CollapseGoConfig::allOne(9));
    playNormal(normalState,4,4);
    playDoubleStart(doubleState,4,4);
    CollapseGoApplyResult normalTermination = terminateAccepted(
      normalState,P_WHITE,CollapseGoAdministrativeTerminationReason::TIMEOUT
    );
    CollapseGoApplyResult doubleTermination = terminateAccepted(
      doubleState,P_WHITE,CollapseGoAdministrativeTerminationReason::TIMEOUT
    );
    testAssert(normalTermination.terminalEvent.has_value());
    testAssert(doubleTermination.terminalEvent.has_value());
    testAssert(*normalTermination.terminalEvent != *doubleTermination.terminalEvent);
    expectStringError([&]() {
      normalTermination.terminalEvent->validateAgainstCommittedState(doubleState);
    });
    expectStringError([&]() {
      doubleTermination.terminalEvent->validateAgainstCommittedState(normalState);
    });
  }

  // Termination-first suppresses a candidate trigger; action-first completes settlement before termination.
  {
    CollapseGoState decision(CollapseGoConfig::allOne(9));
    playPass(decision);
    testAssert(decision.getPhase() == CollapseGoPhase::COLLAPSE_PLAY);
    testAssert(decision.getConsecutivePasses() == 1);

    CollapseGoState terminationFirst(decision);
    CollapseGoApplyResult immediate = terminateAccepted(
      terminationFirst,P_BLACK,CollapseGoAdministrativeTerminationReason::RESIGNATION
    );
    testAssert(immediate.terminalEvent.has_value());
    testAssert(!immediate.settlementTriggered);
    testAssert(terminationFirst.getAtomicActionCount() == 1);
    testAssert(terminationFirst.getConsecutivePasses() == 1);
    testAssert(!terminationFirst.isSettlementCompleted());
    expectRejectedAtomically(
      terminationFirst,P_WHITE,GameAction::pass(),CollapseGoApplyError::TERMINAL_STATE,true
    );

    CollapseGoState actionFirst(decision);
    CollapseGoApplyResult trigger = playPass(actionFirst);
    testAssert(trigger.settlementTriggered);
    testAssert(trigger.settlementReason == CollapseGoSettlementReason::PRE_THRESHOLD_TWO_PASSES);
    testAssert(!trigger.terminalEvent.has_value());
    testAssert(actionFirst.getPhase() == CollapseGoPhase::ORDINARY_PLAY);
    testAssert(actionFirst.isSettlementCompleted());
    testAssert(actionFirst.getConsecutivePasses() == 0);
    testAssert(actionFirst.getRevision() == 2);
    testAssert(actionFirst.getLogPosition() == 2);

    CollapseGoApplyResult afterSettlement = terminateAccepted(
      actionFirst,P_BLACK,CollapseGoAdministrativeTerminationReason::TIMEOUT
    );
    testAssert(afterSettlement.terminalEvent.has_value());
    testAssert(!afterSettlement.settlementTriggered);
    testAssert(afterSettlement.terminalEvent->reason == CollapseGoTerminalReason::TIMEOUT);
    testAssert(actionFirst.getPhase() == CollapseGoPhase::TERMINAL);
    testAssert(actionFirst.isSettlementCompleted());
    testAssert(actionFirst.getAtomicActionCount() == 2);
    testAssert(actionFirst.getRevision() == 3);
    testAssert(actionFirst.getLogPosition() == 3);
    testAssert(actionFirst.getPositionalSuperkoHistory().size() == 4);
    testAssert(actionFirst.getScore() == CollapseGoScore());
    actionFirst.checkConsistency();
  }

  // Pending Double is an exposed administrative boundary and retains its exact unfinished turn state.
  {
    CollapseGoState state(CollapseGoConfig::allOne(9));
    playDoubleStart(state,4,4);
    CollapseGoState before(state);
    testAssert(before.getActor() == P_BLACK);
    testAssert(before.getPendingDouble().has_value());

    CollapseGoApplyResult result = terminateAccepted(
      state,P_WHITE,CollapseGoAdministrativeTerminationReason::TIMEOUT
    );
    testAssert(result.terminalEvent.has_value());
    testAssert(result.terminalEvent->winner == P_BLACK);
    testAssert(result.terminalEvent->loser == P_WHITE);
    testAssert(!result.settlementTriggered);
    testAssert(state.getPhase() == CollapseGoPhase::TERMINAL);
    testAssert(state.getActor() == C_EMPTY);
    testAssert(!state.isSettlementCompleted());
    testAssert(state.getAtomicActionCount() == before.getAtomicActionCount());
    testAssert(state.getConsecutivePasses() == before.getConsecutivePasses());
    testAssert(state.getLedger() == before.getLedger());
    testAssert(state.getPendingDouble() == before.getPendingDouble());
    testAssert(state.getPosition().isEqualForTesting(before.getPosition()));
    testAssert(state.getRemainingQuota(P_BLACK,CollapseGoAbility::DOUBLE_MOVE) == 0);
    testAssert(state.getUsedQuota(P_BLACK,CollapseGoAbility::DOUBLE_MOVE) == 1);
    testAssert(state.getRevision() == before.getRevision() + 1);
    testAssert(state.getLogPosition() == before.getLogPosition() + 1);
    testAssert(state.getPositionalSuperkoHistory().size() ==
      before.getPositionalSuperkoHistory().size() + 1);
    testAssert(state.getPositionalSuperkoHistory().back() ==
      before.getPositionalSuperkoHistory().back());
    state.checkConsistency();
  }

  // Invalid administrative inputs and malformed typed terminal states fail without a partial commit.
  {
    CollapseGoState invalidLoser(CollapseGoConfig::allOne(9));
    expectTerminationRejectedAtomically(
      invalidLoser,C_EMPTY,CollapseGoAdministrativeTerminationReason::RESIGNATION,
      CollapseGoApplyError::INVALID_LOSER
    );
    testAssert(CollapseGoReducer::deriveLegalMask(invalidLoser).any());

    CollapseGoState invalidReason(CollapseGoConfig::allOne(9));
    expectTerminationRejectedAtomically(
      invalidReason,P_BLACK,static_cast<CollapseGoAdministrativeTerminationReason>(-1),
      CollapseGoApplyError::INTERNAL_INVARIANT
    );

    CollapseGoState valid(CollapseGoConfig::allOne(9));
    terminateAccepted(valid,P_BLACK,CollapseGoAdministrativeTerminationReason::RESIGNATION);
    valid.checkConsistency();
    expectTerminationRejectedAtomically(
      valid,C_EMPTY,CollapseGoAdministrativeTerminationReason::TIMEOUT,
      CollapseGoApplyError::TERMINAL_STATE
    );

    CollapseGoState missingTerminal(valid);
    CollapseGoStateTestAccess::clearTerminalState(missingTerminal);
    expectStringError([&]() { missingTerminal.checkConsistency(); });

    CollapseGoState wrongPhase(valid);
    CollapseGoStateTestAccess::setPhase(wrongPhase,CollapseGoPhase::COLLAPSE_PLAY);
    expectStringError([&]() { wrongPhase.checkConsistency(); });

    CollapseGoState wrongActor(valid);
    CollapseGoStateTestAccess::setActor(wrongActor,P_BLACK);
    expectStringError([&]() { wrongActor.checkConsistency(); });

    CollapseGoState wrongRevision(valid);
    CollapseGoStateTestAccess::setRevision(wrongRevision,0);
    expectStringError([&]() { wrongRevision.checkConsistency(); });

    CollapseGoState impossibleSettledAdministrative(CollapseGoConfig::allZero(9));
    terminateAccepted(
      impossibleSettledAdministrative,P_BLACK,
      CollapseGoAdministrativeTerminationReason::TIMEOUT
    );
    CollapseGoStateTestAccess::setSettlementCompleted(impossibleSettledAdministrative,true);
    expectStringError([&]() { impossibleSettledAdministrative.checkConsistency(); });

    CollapseGoState forgedTwoNormalOrdinary(CollapseGoConfig::allZero(9));
    playNormal(forgedTwoNormalOrdinary,0,0);
    playNormal(forgedTwoNormalOrdinary,8,8);
    CollapseGoStateTestAccess::setPhase(
      forgedTwoNormalOrdinary,CollapseGoPhase::ORDINARY_PLAY
    );
    CollapseGoStateTestAccess::setSettlementCompleted(forgedTwoNormalOrdinary,true);
    expectStringError([&]() { forgedTwoNormalOrdinary.checkConsistency(); });

    CollapseGoState forgedTwoNormalAdministrative(CollapseGoConfig::allZero(9));
    playNormal(forgedTwoNormalAdministrative,0,0);
    playNormal(forgedTwoNormalAdministrative,8,8);
    terminateAccepted(
      forgedTwoNormalAdministrative,P_BLACK,
      CollapseGoAdministrativeTerminationReason::TIMEOUT
    );
    CollapseGoStateTestAccess::setSettlementCompleted(forgedTwoNormalAdministrative,true);
    expectStringError([&]() { forgedTwoNormalAdministrative.checkConsistency(); });

    CollapseGoState forgedUnsettledOrdinary(CollapseGoConfig::allZero(9));
    enterOrdinaryPlay(forgedUnsettledOrdinary);
    CollapseGoStateTestAccess::setSettlementCompleted(forgedUnsettledOrdinary,false);
    expectStringError([&]() { forgedUnsettledOrdinary.checkConsistency(); });

    CollapseGoState forgedUnsettledAdministrative(CollapseGoConfig::allZero(9));
    enterOrdinaryPlay(forgedUnsettledAdministrative);
    terminateAccepted(
      forgedUnsettledAdministrative,P_WHITE,
      CollapseGoAdministrativeTerminationReason::TIMEOUT
    );
    CollapseGoStateTestAccess::setSettlementCompleted(forgedUnsettledAdministrative,false);
    expectStringError([&]() { forgedUnsettledAdministrative.checkConsistency(); });

    CollapseGoState invalidTerminalReason(valid);
    CollapseGoStateTestAccess::terminalState(invalidTerminalReason).reason =
      static_cast<CollapseGoTerminalReason>(-1);
    expectStringError([&]() { invalidTerminalReason.checkConsistency(); });

    CollapseGoState invalidWinner(valid);
    CollapseGoStateTestAccess::terminalState(invalidWinner).winner = C_EMPTY;
    expectStringError([&]() { invalidWinner.checkConsistency(); });

    CollapseGoState invalidTerminalLoser(valid);
    CollapseGoStateTestAccess::terminalState(invalidTerminalLoser).loser = P_WHITE;
    expectStringError([&]() { invalidTerminalLoser.checkConsistency(); });

    CollapseGoState administrativeScore(valid);
    CollapseGoStateTestAccess::score(administrativeScore).isScored = true;
    expectStringError([&]() { administrativeScore.checkConsistency(); });

    CollapseGoState forgedAdministrativePenultimate(CollapseGoConfig::allOne(9));
    playNormal(forgedAdministrativePenultimate,4,4);
    terminateAccepted(
      forgedAdministrativePenultimate,P_BLACK,
      CollapseGoAdministrativeTerminationReason::RESIGNATION
    );
    const size_t administrativePenultimateIndex =
      forgedAdministrativePenultimate.getPositionalSuperkoHistory().size() - 2;
    vector<uint8_t> forgedAdministrativeOccupancy = forgedAdministrativePenultimate
      .getPositionalSuperkoHistory().at(administrativePenultimateIndex).getOccupancy();
    forgedAdministrativeOccupancy[0] = static_cast<uint8_t>(C_WHITE);
    CollapseGoStateTestAccess::replacePskOccupancy(
      forgedAdministrativePenultimate,
      administrativePenultimateIndex,
      forgedAdministrativeOccupancy
    );
    expectStringError([&]() { forgedAdministrativePenultimate.checkConsistency(); });

    CollapseGoState forgedAdministrativeSources(CollapseGoConfig::allZero(9));
    playNormal(forgedAdministrativeSources,0,0);
    playNormal(forgedAdministrativeSources,8,8);
    terminateAccepted(
      forgedAdministrativeSources,P_BLACK,
      CollapseGoAdministrativeTerminationReason::RESIGNATION
    );
    CollapseGoStateTestAccess::swapStoneSources(
      forgedAdministrativeSources,0,8 + 8 * 9
    );
    expectStringError([&]() { forgedAdministrativeSources.checkConsistency(); });

    CollapseGoState replayedSource(CollapseGoConfig::allZero(9));
    playNormal(replayedSource,0,0);
    playNormal(replayedSource,1,0);
    playNormal(replayedSource,2,0);
    playNormal(replayedSource,0,1);
    testAssert(replayedSource.getPosition().getColor(0,0) == C_EMPTY);
    playNormal(replayedSource,1,1);
    playNormal(replayedSource,8,8);
    playNormal(replayedSource,0,0);
    testAssert(replayedSource.getPosition().getColor(1,0) == C_EMPTY);
    terminateAccepted(
      replayedSource,P_WHITE,
      CollapseGoAdministrativeTerminationReason::RESIGNATION
    );
    CollapseGoStateTestAccess::relabelStoneSource(
      replayedSource,
      0,
      CollapseGoStoneSource(1,GameActionKind::NORMAL,nullopt)
    );
    expectStringError([&]() { replayedSource.checkConsistency(); });

    CollapseGoState relabeledSpecialAsNormal(CollapseGoConfig::allOne(9));
    playDoubleStart(relabeledSpecialAsNormal,4,4);
    playPass(relabeledSpecialAsNormal);
    terminateAccepted(
      relabeledSpecialAsNormal,P_BLACK,
      CollapseGoAdministrativeTerminationReason::RESIGNATION
    );
    CollapseGoStateTestAccess::relabelStoneSource(
      relabeledSpecialAsNormal,
      4 + 4 * 9,
      CollapseGoStoneSource(1,GameActionKind::NORMAL,nullopt)
    );
    CollapseGoStateTestAccess::ledgerEntry(
      relabeledSpecialAsNormal,0
    ).stoneState = CollapseGoLedgerStoneState::CAPTURED;
    expectStringError([&]() { relabeledSpecialAsNormal.checkConsistency(); });

    CollapseGoState pending(CollapseGoConfig::allOne(9));
    playDoubleStart(pending,4,4);
    terminateAccepted(pending,P_BLACK,CollapseGoAdministrativeTerminationReason::TIMEOUT);
    pending.checkConsistency();

    CollapseGoState missingTerminalPending(pending);
    CollapseGoStateTestAccess::clearPendingDouble(missingTerminalPending);
    expectStringError([&]() { missingTerminalPending.checkConsistency(); });

    CollapseGoState mismatchedTerminalPending(pending);
    CollapseGoStateTestAccess::setPendingDouble(mismatchedTerminalPending,P_WHITE,1,1);
    expectStringError([&]() { mismatchedTerminalPending.checkConsistency(); });
  }

  // Two new ordinary-play passes score the current stable board and append both action and terminal occupancies.
  {
    CollapseGoState state(CollapseGoConfig::allOne(9));
    enterOrdinaryPlay(state);
    playNormal(state,0,1);
    playNormal(state,8,8);
    playNormal(state,1,0);
    playNormal(state,8,7);

    CollapseGoApplyResult firstPass = playPass(state);
    testAssert(firstPass.positionalSuperkoAppends == 1);
    testAssert(!firstPass.terminalScoreEventEmitted);
    testAssert(state.getPhase() == CollapseGoPhase::ORDINARY_PLAY);
    testAssert(state.getPositionalSuperkoHistory().size() == 8);

    CollapseGoApplyResult finalPass = playPass(state);
    testAssert(finalPass.accepted);
    testAssert(finalPass.positionalSuperkoAppends == 2);
    testAssert(finalPass.terminalScoreEventEmitted);
    testAssert(finalPass.terminalEvent.has_value());
    testAssert(!finalPass.settlementTriggered);
    testAssert(state.getPhase() == CollapseGoPhase::TERMINAL);
    testAssert(state.getActor() == C_EMPTY);
    testAssert(state.getAtomicActionCount() == 8);
    testAssert(state.getRevision() == 8);
    testAssert(state.getStableTerminalEventCount() == 1);
    testAssert(state.getLogPosition() == 9);
    testAssert(state.getConsecutivePasses() == 2);
    testAssert(state.getPositionalSuperkoHistory().size() == 10);
    testAssert(state.getPositionalSuperkoHistory().at(7) == state.getPositionalSuperkoHistory().at(8));
    testAssert(state.getPositionalSuperkoHistory().at(8) == state.getPositionalSuperkoHistory().at(9));
    state.checkConsistency();

    const CollapseGoScore& score = state.getScore();
    testAssert(score.isScored);
    testAssert(score.blackStones == 2);
    testAssert(score.whiteStones == 2);
    testAssert(score.blackTerritory == 1);
    testAssert(score.whiteTerritory == 0);
    testAssert(score.blackScoreNumerator == 6);
    testAssert(score.whiteScoreNumerator == 19);
    testAssert(score.getBlackScore() == 3.0);
    testAssert(score.getWhiteScore() == 9.5);
    testAssert(score.winner == P_WHITE);
    testAssert(score.marginNumerator == 13);
    testAssert(score.getMargin() == 6.5);

    testAssert(state.getTerminalState().has_value());
    const CollapseGoTerminalState& terminal = *state.getTerminalState();
    testAssert(terminal.reason == CollapseGoTerminalReason::SCORE);
    testAssert(terminal.winner == P_WHITE);
    testAssert(terminal.loser == P_BLACK);
    const CollapseGoTerminalEvent& event = *finalPass.terminalEvent;
    testAssert(event.reason == CollapseGoTerminalReason::SCORE);
    testAssert(event.winner == terminal.winner);
    testAssert(event.loser == terminal.loser);
    testAssert(event.score == score);
    testAssert(event.settlementCompleted);
    testAssert(event.stablePosition.isEqualForTesting(state.getPosition()));
    testAssert(event.stableOccupancy == state.getPosition().getRowMajorOccupancy());
    testAssert(event.positionalSuperkoHistoryIndex == 9);
    testAssert(event.revision == 8);
    testAssert(event.logPosition == 9);
    CollapseGoTerminalEvent expectedEvent =
      CollapseGoTerminalEvent::fromCommittedState(state);
    expectedEvent.validateAgainstCommittedState(state);
    testAssert(event == expectedEvent);

    CollapseGoTerminalEvent forgedReason(event);
    forgedReason.reason = CollapseGoTerminalReason::TIMEOUT;
    expectStringError([&]() { forgedReason.validateAgainstCommittedState(state); });

    CollapseGoTerminalEvent forgedWinner(event);
    forgedWinner.winner = P_BLACK;
    expectStringError([&]() { forgedWinner.validateAgainstCommittedState(state); });

    CollapseGoTerminalEvent forgedLoser(event);
    forgedLoser.loser = P_WHITE;
    expectStringError([&]() { forgedLoser.validateAgainstCommittedState(state); });

    CollapseGoTerminalEvent forgedEventScore(event);
    forgedEventScore.score.marginNumerator++;
    expectStringError([&]() { forgedEventScore.validateAgainstCommittedState(state); });

    CollapseGoTerminalEvent forgedSettlementProvenance(event);
    forgedSettlementProvenance.settlementCompleted = false;
    expectStringError([&]() {
      forgedSettlementProvenance.validateAgainstCommittedState(state);
    });

    CollapseGoTerminalEvent forgedStablePosition(event);
    forgedStablePosition.stablePosition.removeStone(0 + 1 * 9);
    expectStringError([&]() { forgedStablePosition.validateAgainstCommittedState(state); });

    CollapseGoTerminalEvent forgedEventOccupancy(event);
    forgedEventOccupancy.stableOccupancy[0] =
      forgedEventOccupancy.stableOccupancy[0] == static_cast<uint8_t>(C_BLACK) ?
      static_cast<uint8_t>(C_EMPTY) : static_cast<uint8_t>(C_BLACK);
    expectStringError([&]() { forgedEventOccupancy.validateAgainstCommittedState(state); });

    for(int64_t CollapseGoTerminalEvent::* metadataField: {
      &CollapseGoTerminalEvent::positionalSuperkoHistoryIndex,
      &CollapseGoTerminalEvent::revision,
      &CollapseGoTerminalEvent::logPosition,
    }) {
      CollapseGoTerminalEvent staleEvent(event);
      staleEvent.*metadataField -= 1;
      expectStringError([&]() { staleEvent.validateAgainstCommittedState(state); });
    }

    CollapseGoState scoredState(state);

    CollapseGoState extraOrdinaryPass(scoredState);
    const size_t terminalHistoryIndex =
      extraOrdinaryPass.getPositionalSuperkoHistory().size() - 1;
    CollapseGoStateTestAccess::insertPskOccupancy(
      extraOrdinaryPass,
      terminalHistoryIndex,
      extraOrdinaryPass.getPositionalSuperkoHistory().at(terminalHistoryIndex).getOccupancy()
    );
    CollapseGoStateTestAccess::setAtomicActionCount(
      extraOrdinaryPass,extraOrdinaryPass.getAtomicActionCount() + 1
    );
    CollapseGoStateTestAccess::setRevision(
      extraOrdinaryPass,extraOrdinaryPass.getRevision() + 1
    );
    CollapseGoStateTestAccess::setLogPosition(
      extraOrdinaryPass,extraOrdinaryPass.getLogPosition() + 1
    );
    expectStringError([&]() { extraOrdinaryPass.checkConsistency(); });

    CollapseGoState relabeledScore(scoredState);
    CollapseGoStateTestAccess::terminalState(relabeledScore).reason =
      CollapseGoTerminalReason::TIMEOUT;
    CollapseGoStateTestAccess::score(relabeledScore) = CollapseGoScore();
    CollapseGoStateTestAccess::setConsecutivePasses(relabeledScore,1);
    CollapseGoStateTestAccess::setRevision(
      relabeledScore,relabeledScore.getAtomicActionCount() + 1
    );
    expectStringError([&]() { relabeledScore.checkConsistency(); });

    CollapseGoState forgedRelabeledScore(scoredState);
    CollapseGoStateTestAccess::terminalState(forgedRelabeledScore).reason =
      CollapseGoTerminalReason::TIMEOUT;
    CollapseGoStateTestAccess::score(forgedRelabeledScore) = CollapseGoScore();
    CollapseGoStateTestAccess::setConsecutivePasses(forgedRelabeledScore,0);
    CollapseGoStateTestAccess::setRevision(
      forgedRelabeledScore,forgedRelabeledScore.getAtomicActionCount() + 1
    );
    const size_t forgedRelabelIndex =
      forgedRelabeledScore.getPositionalSuperkoHistory().size() - 3;
    vector<uint8_t> forgedRelabelOccupancy = forgedRelabeledScore
      .getPositionalSuperkoHistory().at(forgedRelabelIndex).getOccupancy();
    forgedRelabelOccupancy[0] = static_cast<uint8_t>(C_BLACK);
    CollapseGoStateTestAccess::replacePskOccupancy(
      forgedRelabeledScore,forgedRelabelIndex,forgedRelabelOccupancy
    );
    expectStringError([&]() { forgedRelabeledScore.checkConsistency(); });

    CollapseGoState forgedSourceAndPsk(CollapseGoConfig::allZero(9));
    playPass(forgedSourceAndPsk);
    playPass(forgedSourceAndPsk);
    playNormal(forgedSourceAndPsk,0,0);
    playPass(forgedSourceAndPsk);
    playPass(forgedSourceAndPsk);
    testAssert(forgedSourceAndPsk.getPhase() == CollapseGoPhase::TERMINAL);
    CollapseGoStateTestAccess::terminalState(forgedSourceAndPsk).reason =
      CollapseGoTerminalReason::TIMEOUT;
    CollapseGoStateTestAccess::score(forgedSourceAndPsk) = CollapseGoScore();
    CollapseGoStateTestAccess::setConsecutivePasses(forgedSourceAndPsk,0);
    CollapseGoStateTestAccess::setRevision(
      forgedSourceAndPsk,forgedSourceAndPsk.getAtomicActionCount() + 1
    );
    CollapseGoStateTestAccess::relabelStoneSource(
      forgedSourceAndPsk,
      0,
      CollapseGoStoneSource(5,GameActionKind::NORMAL,nullopt)
    );
    vector<uint8_t> forgedSourcePriorOccupancy = forgedSourceAndPsk
      .getPositionalSuperkoHistory().at(4).getOccupancy();
    forgedSourcePriorOccupancy[0] = static_cast<uint8_t>(C_EMPTY);
    CollapseGoStateTestAccess::replacePskOccupancy(
      forgedSourceAndPsk,4,forgedSourcePriorOccupancy
    );
    expectStringError([&]() { forgedSourceAndPsk.checkConsistency(); });

    CollapseGoState forgedEarlierScoreBoundary(CollapseGoConfig::allZero(9));
    playPass(forgedEarlierScoreBoundary);
    playPass(forgedEarlierScoreBoundary);
    playNormal(forgedEarlierScoreBoundary,0,0);
    playPass(forgedEarlierScoreBoundary);
    playPass(forgedEarlierScoreBoundary);
    CollapseGoStateTestAccess::terminalState(forgedEarlierScoreBoundary).reason =
      CollapseGoTerminalReason::TIMEOUT;
    CollapseGoStateTestAccess::score(forgedEarlierScoreBoundary) = CollapseGoScore();
    CollapseGoStateTestAccess::setConsecutivePasses(forgedEarlierScoreBoundary,0);
    CollapseGoStateTestAccess::setRevision(
      forgedEarlierScoreBoundary,forgedEarlierScoreBoundary.getAtomicActionCount() + 1
    );
    CollapseGoStateTestAccess::relabelStoneSource(
      forgedEarlierScoreBoundary,
      0,
      CollapseGoStoneSource(5,GameActionKind::NORMAL,nullopt)
    );
    const vector<uint8_t> emptyOccupancy = forgedEarlierScoreBoundary
      .getPositionalSuperkoHistory().at(0).getOccupancy();
    CollapseGoStateTestAccess::replacePskOccupancy(
      forgedEarlierScoreBoundary,3,emptyOccupancy
    );
    CollapseGoStateTestAccess::replacePskOccupancy(
      forgedEarlierScoreBoundary,4,emptyOccupancy
    );
    expectStringError([&]() { forgedEarlierScoreBoundary.checkConsistency(); });

    CollapseGoState suppressedEarlyTrigger(CollapseGoConfig::allZero(9));
    playPass(suppressedEarlyTrigger);
    playPass(suppressedEarlyTrigger);
    int placed = 0;
    for(int point = 0; point < 9 * 9 && placed < 32; point++) {
      const int x = point % 9;
      const int y = point / 9;
      if((x + y) % 2 != 0)
        continue;
      playNormal(suppressedEarlyTrigger,x,y);
      placed += 1;
    }
    testAssert(placed == 32);
    testAssert(suppressedEarlyTrigger.getAtomicActionCount() == 34);
    testAssert(suppressedEarlyTrigger.getPhase() == CollapseGoPhase::ORDINARY_PLAY);
    CollapseGoStateTestAccess::relabelStoneSource(
      suppressedEarlyTrigger,
      0,
      CollapseGoStoneSource(2,GameActionKind::NORMAL,nullopt)
    );
    expectStringError([&]() { suppressedEarlyTrigger.checkConsistency(); });

    CollapseGoState impossibleScoreProvenance(scoredState);
    CollapseGoStateTestAccess::setAtomicActionCount(impossibleScoreProvenance,2);
    CollapseGoStateTestAccess::setRevision(impossibleScoreProvenance,2);
    CollapseGoStateTestAccess::setLogPosition(impossibleScoreProvenance,3);
    CollapseGoStateTestAccess::resetPskToRepeatedCurrent(impossibleScoreProvenance,4);
    expectStringError([&]() { impossibleScoreProvenance.checkConsistency(); });

    CollapseGoState forgedFirstOrdinaryPass(scoredState);
    const size_t firstOrdinaryPassIndex =
      forgedFirstOrdinaryPass.getPositionalSuperkoHistory().size() - 4;
    vector<uint8_t> forgedFirstPassOccupancy = forgedFirstOrdinaryPass
      .getPositionalSuperkoHistory().at(firstOrdinaryPassIndex).getOccupancy();
    forgedFirstPassOccupancy[static_cast<size_t>(4 + 4 * 9)] = static_cast<uint8_t>(C_BLACK);
    CollapseGoStateTestAccess::replacePskOccupancy(
      forgedFirstOrdinaryPass,firstOrdinaryPassIndex,forgedFirstPassOccupancy
    );
    expectStringError([&]() { forgedFirstOrdinaryPass.checkConsistency(); });

    for(CollapseGoAdministrativeTerminationReason reason: {
      CollapseGoAdministrativeTerminationReason::RESIGNATION,
      CollapseGoAdministrativeTerminationReason::TIMEOUT,
    }) {
      expectTerminationRejectedAtomically(
        state,P_BLACK,reason,CollapseGoApplyError::TERMINAL_STATE
      );
      testAssert(state.isEqualForTesting(scoredState));
    }

    CollapseGoState mismatchedScoreWinner(scoredState);
    CollapseGoTerminalState& mismatchedTerminal =
      CollapseGoStateTestAccess::terminalState(mismatchedScoreWinner);
    mismatchedTerminal.winner = P_BLACK;
    mismatchedTerminal.loser = P_WHITE;
    expectStringError([&]() { mismatchedScoreWinner.checkConsistency(); });

    for(int CollapseGoScore::* field: {
      &CollapseGoScore::blackStones,
      &CollapseGoScore::whiteStones,
      &CollapseGoScore::blackTerritory,
      &CollapseGoScore::whiteTerritory,
      &CollapseGoScore::blackScoreNumerator,
      &CollapseGoScore::whiteScoreNumerator,
      &CollapseGoScore::marginNumerator,
    }) {
      CollapseGoState forgedScore(scoredState);
      CollapseGoStateTestAccess::score(forgedScore).*field += 1;
      expectStringError([&]() { forgedScore.checkConsistency(); });
      expectStringError([&]() {
        (void)CollapseGoTerminalEvent::fromCommittedState(forgedScore);
      });
    }
    CollapseGoState forgedScoreWinner(scoredState);
    CollapseGoStateTestAccess::score(forgedScoreWinner).winner = P_BLACK;
    expectStringError([&]() { forgedScoreWinner.checkConsistency(); });
    expectStringError([&]() {
      (void)CollapseGoTerminalEvent::fromCommittedState(forgedScoreWinner);
    });

    CollapseGoState forgedPenultimatePsk(scoredState);
    const size_t penultimateIndex =
      forgedPenultimatePsk.getPositionalSuperkoHistory().size() - 2;
    vector<uint8_t> forgedPenultimateOccupancy =
      forgedPenultimatePsk.getPositionalSuperkoHistory().at(penultimateIndex).getOccupancy();
    forgedPenultimateOccupancy[static_cast<size_t>(4 + 4 * 9)] = static_cast<uint8_t>(C_BLACK);
    CollapseGoStateTestAccess::replacePskOccupancy(
      forgedPenultimatePsk,penultimateIndex,forgedPenultimateOccupancy
    );
    expectStringError([&]() { forgedPenultimatePsk.checkConsistency(); });
    expectStringError([&]() {
      (void)CollapseGoTerminalEvent::fromCommittedState(forgedPenultimatePsk);
    });
  }

  // A reachable one-stone position scores the whole remaining 9x9 area for Black.
  {
    CollapseGoState state(CollapseGoConfig::allOne(9));
    enterOrdinaryPlay(state);
    playNormal(state,4,4);
    playPass(state);
    CollapseGoApplyResult finalPass = playPass(state);

    testAssert(finalPass.terminalScoreEventEmitted);
    testAssert(finalPass.terminalEvent.has_value());
    testAssert(state.getPhase() == CollapseGoPhase::TERMINAL);
    state.checkConsistency();

    const CollapseGoScore& score = state.getScore();
    testAssert(score.isScored);
    testAssert(score.blackStones == 1);
    testAssert(score.whiteStones == 0);
    testAssert(score.blackTerritory == 80);
    testAssert(score.whiteTerritory == 0);
    testAssert(score.blackScoreNumerator == 162);
    testAssert(score.whiteScoreNumerator == 15);
    testAssert(score.getBlackScore() == 81.0);
    testAssert(score.getWhiteScore() == 7.5);
    testAssert(score.winner == P_BLACK);
    testAssert(score.marginNumerator == 147);
    testAssert(score.getMargin() == 73.5);

    testAssert(state.getTerminalState().has_value());
    const CollapseGoTerminalState& terminal = *state.getTerminalState();
    testAssert(terminal.reason == CollapseGoTerminalReason::SCORE);
    testAssert(terminal.winner == P_BLACK);
    testAssert(terminal.loser == P_WHITE);
    testAssert(finalPass.terminalEvent->winner == P_BLACK);
    testAssert(finalPass.terminalEvent->loser == P_WHITE);
    testAssert(finalPass.terminalEvent->score == score);
    const PositionalSuperkoHistory& history = state.getPositionalSuperkoHistory();
    testAssert(history.at(history.size() - 1) == history.at(history.size() - 2));
  }

  // Reducer-produced action-before-automatic-transition snapshots are audit-only, not decisions.
  {
    CollapseGoState thresholdState(CollapseGoConfig::allOne(9));
    const int threshold = thresholdState.getConfig().getThreshold();
    playToAtomicActionCount(thresholdState,threshold - 1);
    CollapseGoApplyResult thresholdTrigger = playNormal(thresholdState,8,8);
    testAssert(thresholdTrigger.settlementTriggered);
    testAssert(thresholdTrigger.settlementReason == CollapseGoSettlementReason::THRESHOLD);
    testAssert(thresholdTrigger.atomicStateSnapshot.has_value());
    const CollapseGoState& thresholdSnapshot = *thresholdTrigger.atomicStateSnapshot;
    testAssert(thresholdSnapshot.getPhase() == CollapseGoPhase::COLLAPSE_PLAY);
    testAssert(thresholdSnapshot.getAtomicActionCount() == threshold);
    testAssert(thresholdSnapshot.getConsecutivePasses() == 0);
    assertNonDecisionSnapshotFailsClosed(thresholdSnapshot);

    CollapseGoState earlyPassState(CollapseGoConfig::allOne(9));
    playPass(earlyPassState);
    CollapseGoApplyResult earlyPassTrigger = playPass(earlyPassState);
    testAssert(earlyPassTrigger.settlementTriggered);
    testAssert(earlyPassTrigger.settlementReason ==
      CollapseGoSettlementReason::PRE_THRESHOLD_TWO_PASSES);
    testAssert(earlyPassTrigger.atomicStateSnapshot.has_value());
    const CollapseGoState& earlyPassSnapshot = *earlyPassTrigger.atomicStateSnapshot;
    testAssert(earlyPassSnapshot.getPhase() == CollapseGoPhase::COLLAPSE_PLAY);
    testAssert(earlyPassSnapshot.getAtomicActionCount() < threshold);
    testAssert(earlyPassSnapshot.getConsecutivePasses() == 2);
    assertNonDecisionSnapshotFailsClosed(earlyPassSnapshot);

    CollapseGoState scoringState(CollapseGoConfig::allOne(9));
    enterOrdinaryPlay(scoringState);
    playPass(scoringState);
    CollapseGoApplyResult scoringTrigger = playPass(scoringState);
    testAssert(scoringTrigger.terminalScoreEventEmitted);
    testAssert(scoringTrigger.atomicStateSnapshot.has_value());
    const CollapseGoState& scoringSnapshot = *scoringTrigger.atomicStateSnapshot;
    testAssert(scoringSnapshot.getPhase() == CollapseGoPhase::ORDINARY_PLAY);
    testAssert(scoringSnapshot.getConsecutivePasses() == 2);
    testAssert(!scoringSnapshot.getScore().isScored);
    assertNonDecisionSnapshotFailsClosed(scoringSnapshot);
  }

  // Initial masks use the fixed centered canvas, expose all funded families, and exhaustively match apply.
  {
    for(int boardSize: {9,13,19}) {
      CollapseGoState state(CollapseGoConfig::allOne(boardSize));
      CollapseGoLegalMask mask = assertLegalMaskMatchesApply(state);
      testAssert(mask.count() == static_cast<size_t>(4 * boardSize * boardSize + 1));
      testAssert(mask.test(static_cast<size_t>(GameAction::PASS_ACTION_ID)));
      for(GameActionKind kind: {
        GameActionKind::NORMAL,
        GameActionKind::IMMORTAL,
        GameActionKind::DOUBLE_START,
        GameActionKind::EIGHTWAY,
      }) {
        testAssert(mask.test(static_cast<size_t>(actionIdAt(kind,boardSize,0,0))));
        bool canvasCornerIsLegal = mask.test(static_cast<size_t>(
          GameAction::fromCanvas(kind,0,0).getActionId()
        ));
        testAssert(canvasCornerIsLegal == (boardSize == 19));
      }
    }

    CollapseGoState exhausted(CollapseGoConfig::allZero(13));
    CollapseGoLegalMask exhaustedMask = assertLegalMaskMatchesApply(exhausted);
    testAssert(exhaustedMask.count() == 13 * 13 + 1);
    testAssert(exhaustedMask.test(static_cast<size_t>(actionIdAt(
      GameActionKind::NORMAL,13,6,6
    ))));
    for(GameActionKind kind: {
      GameActionKind::IMMORTAL,
      GameActionKind::DOUBLE_START,
      GameActionKind::EIGHTWAY,
    })
      testAssert(!exhaustedMask.test(static_cast<size_t>(actionIdAt(kind,13,6,6))));
  }

  // Pending Double masks on every supported size contain only legal NORMAL continuations and PASS.
  {
    for(int boardSize: {9,13,19}) {
      CollapseGoState state(CollapseGoConfig::allOne(boardSize));
      int center = boardSize / 2;
      playDoubleStart(state,center,center);
      CollapseGoLegalMask mask = assertLegalMaskMatchesApply(state);
      testAssert(mask.count() == static_cast<size_t>(boardSize * boardSize));
      testAssert(mask.test(static_cast<size_t>(GameAction::PASS_ACTION_ID)));
      testAssert(!mask.test(static_cast<size_t>(actionIdAt(
        GameActionKind::NORMAL,boardSize,center,center
      ))));
      testAssert(mask.test(static_cast<size_t>(actionIdAt(
        GameActionKind::NORMAL,boardSize,0,0
      ))));
      for(GameActionKind kind: {
        GameActionKind::IMMORTAL,
        GameActionKind::DOUBLE_START,
        GameActionKind::EIGHTWAY,
      })
        testAssert(!mask.test(static_cast<size_t>(actionIdAt(kind,boardSize,0,0))));
    }
  }

  // The T-2, T-1, and pending-T continuation boundaries derive exact Double threshold legality.
  {
    CollapseGoState beforeDoubleBoundary(CollapseGoConfig::allOne(9));
    const int threshold = beforeDoubleBoundary.getConfig().getThreshold();
    playToAtomicActionCount(beforeDoubleBoundary,threshold - 2);
    CollapseGoLegalMask beforeMask = assertLegalMaskMatchesApply(beforeDoubleBoundary);
    testAssert(beforeMask.test(static_cast<size_t>(actionIdAt(
      GameActionKind::DOUBLE_START,9,8,8
    ))));

    CollapseGoState tooLate(beforeDoubleBoundary);
    playNormal(tooLate,8,8);
    testAssert(tooLate.getAtomicActionCount() == threshold - 1);
    CollapseGoLegalMask tooLateMask = assertLegalMaskMatchesApply(tooLate);
    testAssert(!tooLateMask.test(static_cast<size_t>(actionIdAt(
      GameActionKind::DOUBLE_START,9,7,8
    ))));
    testAssert(tooLateMask.test(static_cast<size_t>(actionIdAt(
      GameActionKind::IMMORTAL,9,7,8
    ))));
    testAssert(tooLateMask.test(static_cast<size_t>(actionIdAt(
      GameActionKind::EIGHTWAY,9,7,8
    ))));

    CollapseGoState pendingAtThreshold(beforeDoubleBoundary);
    playDoubleStart(pendingAtThreshold,8,8);
    testAssert(pendingAtThreshold.getAtomicActionCount() == threshold - 1);
    CollapseGoLegalMask pendingMask = assertLegalMaskMatchesApply(pendingAtThreshold);
    testAssert(pendingMask.test(static_cast<size_t>(actionIdAt(
      GameActionKind::NORMAL,9,7,8
    ))));
    testAssert(pendingMask.test(static_cast<size_t>(GameAction::PASS_ACTION_ID)));
    for(GameActionKind kind: {
      GameActionKind::IMMORTAL,
      GameActionKind::DOUBLE_START,
      GameActionKind::EIGHTWAY,
    })
      testAssert(!pendingMask.test(static_cast<size_t>(actionIdAt(kind,9,7,8))));
  }

  // Ordinary play exposes only NORMAL and PASS, while terminal derivation is exactly all false.
  {
    CollapseGoState state(CollapseGoConfig::allOne(9));
    enterOrdinaryPlay(state);
    CollapseGoLegalMask ordinaryMask = assertLegalMaskMatchesApply(state);
    testAssert(ordinaryMask.count() == 9 * 9 + 1);
    testAssert(ordinaryMask.test(static_cast<size_t>(actionIdAt(
      GameActionKind::NORMAL,9,4,4
    ))));
    for(GameActionKind kind: {
      GameActionKind::IMMORTAL,
      GameActionKind::DOUBLE_START,
      GameActionKind::EIGHTWAY,
    })
      testAssert(!ordinaryMask.test(static_cast<size_t>(actionIdAt(kind,9,4,4))));

    playPass(state);
    CollapseGoLegalMask onePassMask = assertLegalMaskMatchesApply(state);
    testAssert(onePassMask.test(static_cast<size_t>(GameAction::PASS_ACTION_ID)));
    CollapseGoApplyResult terminalPass = playPass(state);
    testAssert(terminalPass.terminalScoreEventEmitted);
    CollapseGoLegalMask terminalMask = assertLegalMaskMatchesApply(state);
    testAssert(terminalMask.none());
  }

  // Family-specific survival and occupancy-only PSK decisions are reflected at every action ID.
  {
    CollapseGoState suicide(CollapseGoConfig::allOne(9));
    playNormal(suicide,8,8); playNormal(suicide,1,2);
    playNormal(suicide,8,7); playNormal(suicide,3,2);
    playNormal(suicide,7,8); playNormal(suicide,2,1);
    playNormal(suicide,7,7); playNormal(suicide,2,3);
    CollapseGoLegalMask suicideMask = assertLegalMaskMatchesApply(suicide);
    testAssert(!suicideMask.test(static_cast<size_t>(actionIdAt(
      GameActionKind::NORMAL,9,2,2
    ))));
    testAssert(!suicideMask.test(static_cast<size_t>(actionIdAt(
      GameActionKind::DOUBLE_START,9,2,2
    ))));
    testAssert(suicideMask.test(static_cast<size_t>(actionIdAt(
      GameActionKind::IMMORTAL,9,2,2
    ))));
    testAssert(suicideMask.test(static_cast<size_t>(actionIdAt(
      GameActionKind::EIGHTWAY,9,2,2
    ))));

    CollapseGoState psk(CollapseGoConfig::allOne(9));
    playNormal(psk,1,2); playNormal(psk,1,1);
    playNormal(psk,3,2); playNormal(psk,3,1);
    playNormal(psk,2,3); playNormal(psk,2,0);
    playNormal(psk,8,8); playNormal(psk,2,2);
    playNormal(psk,2,1);
    CollapseGoLegalMask pskMask = assertLegalMaskMatchesApply(psk);
    for(GameActionKind kind: {
      GameActionKind::NORMAL,
      GameActionKind::IMMORTAL,
      GameActionKind::DOUBLE_START,
      GameActionKind::EIGHTWAY,
    })
      testAssert(!pskMask.test(static_cast<size_t>(actionIdAt(kind,9,2,2))));
  }

  // Immortal protection and live Eightway capture states retain exact derived legality.
  {
    CollapseGoState immortal(CollapseGoConfig::allOne(19));
    playImmortalTrueEyePrefix(immortal);
    CollapseGoLegalMask beforeImmortal = assertLegalMaskMatchesApply(immortal);
    testAssert(!beforeImmortal.test(static_cast<size_t>(actionIdAt(
      GameActionKind::NORMAL,19,9,9
    ))));
    testAssert(beforeImmortal.test(static_cast<size_t>(actionIdAt(
      GameActionKind::IMMORTAL,19,9,9
    ))));
    testAssert(!beforeImmortal.test(static_cast<size_t>(actionIdAt(
      GameActionKind::DOUBLE_START,19,9,9
    ))));
    testAssert(!beforeImmortal.test(static_cast<size_t>(actionIdAt(
      GameActionKind::EIGHTWAY,19,9,9
    ))));
    playImmortal(immortal,9,9);
    CollapseGoLegalMask armedImmortal = assertLegalMaskMatchesApply(immortal);
    for(GameActionKind kind: {
      GameActionKind::NORMAL,
      GameActionKind::IMMORTAL,
      GameActionKind::DOUBLE_START,
      GameActionKind::EIGHTWAY,
    })
      testAssert(!armedImmortal.test(static_cast<size_t>(actionIdAt(kind,19,9,9))));

    CollapseGoConfig captureConfig(9,CollapseGoQuotas(0,0,1),CollapseGoQuotas());
    CollapseGoState eightwayCapture(captureConfig);
    playEightway(eightwayCapture,4,4);
    const pair<int,int> ring[8] = {
      {3,3},{4,3},{5,3},{3,4},{5,4},{3,5},{4,5},{5,5},
    };
    for(int index = 0; index < 7; index++) {
      playNormal(eightwayCapture,ring[index].first,ring[index].second);
      playNormal(eightwayCapture,index,8);
    }
    CollapseGoLegalMask beforeCapture = assertLegalMaskMatchesApply(eightwayCapture);
    testAssert(beforeCapture.test(static_cast<size_t>(actionIdAt(
      GameActionKind::NORMAL,9,ring[7].first,ring[7].second
    ))));
    CollapseGoApplyResult capture = playNormal(
      eightwayCapture,ring[7].first,ring[7].second
    );
    testAssert(capture.capturedStones == vector<Loc>({Location::getLoc(4,4,9)}));
    testAssert(eightwayCapture.getLedger().at(0).stoneState ==
      CollapseGoLedgerStoneState::CAPTURED);
    assertLegalMaskMatchesApply(eightwayCapture);
  }

  // Active Immortal/Eightway topology and full PSK legality transform equivariantly under all D4 maps.
  {
    ImmortalD4Episode referenceEpisode = runEightwayD4Episode(0);
    CollapseGoLegalMask referenceMask = assertLegalMaskMatchesApply(
      referenceEpisode.placementState
    );
    assertD4LegalMask(referenceMask,referenceMask,0);
    for(int symmetry = 1; symmetry < 8; symmetry++) {
      ImmortalD4Episode transformedEpisode = runEightwayD4Episode(symmetry);
      CollapseGoLegalMask transformedMask = assertLegalMaskMatchesApply(
        transformedEpisode.placementState
      );
      assertD4LegalMask(referenceMask,transformedMask,symmetry);
      assertD4LegalMask(
        transformedMask,referenceMask,GameAction::inverseSymmetry(symmetry)
      );
    }
  }

  // A pending-Double checkpoint restores by assignment and replays D/E/I settlement exactly.
  {
    const int boardSize = 9;
    const vector<CollapseGoReplayStep> prefix = {
      {P_BLACK,specialAction(GameActionKind::IMMORTAL,boardSize,0,0)},
      {P_WHITE,specialAction(GameActionKind::EIGHTWAY,boardSize,8,8)},
      {P_BLACK,specialAction(GameActionKind::DOUBLE_START,boardSize,1,0)},
    };
    const vector<CollapseGoReplayStep> suffix = {
      {P_BLACK,normalAction(boardSize,2,0)},
      {P_WHITE,GameAction::pass()},
      {P_BLACK,GameAction::pass()},
    };

    CollapseGoState checkpoint(CollapseGoConfig::allOne(boardSize));
    for(const CollapseGoReplayStep& step: prefix)
      applyAccepted(checkpoint,step.first,step.second);
    checkpoint.checkConsistency();
    testAssert(checkpoint.getAtomicActionCount() == 3);
    testAssert(checkpoint.getRevision() == 3);
    testAssert(checkpoint.getLogPosition() == 3);
    testAssert(checkpoint.getPhase() == CollapseGoPhase::COLLAPSE_PLAY);
    testAssert(checkpoint.getActor() == P_BLACK);
    testAssert(checkpoint.getPendingDouble().has_value());
    testAssert(checkpoint.getPendingDouble()->owner == P_BLACK);
    testAssert(checkpoint.getPendingDouble()->originActionNumber == 3);
    testAssert(checkpoint.getLedger().size() == 3);
    CollapseGoLegalMask checkpointMask = deriveStableReplayMask(checkpoint);
    testAssert(checkpointMask.count() == 79);
    testAssert(checkpointMask.test(static_cast<size_t>(actionIdAt(
      GameActionKind::NORMAL,boardSize,2,0
    ))));
    testAssert(checkpointMask.test(static_cast<size_t>(GameAction::PASS_ACTION_ID)));
    for(GameActionKind kind: {
      GameActionKind::IMMORTAL,
      GameActionKind::DOUBLE_START,
      GameActionKind::EIGHTWAY,
    })
      testAssert(!checkpointMask.test(static_cast<size_t>(actionIdAt(kind,boardSize,2,0))));

    CollapseGoState immutableCheckpoint(checkpoint);
    CollapseGoSuffixRecord replay = assertDeterministicSuffixReplay(checkpoint,prefix,suffix);
    testAssert(checkpoint.isEqualForTesting(immutableCheckpoint));
    testAssert(replay.legalMasks.front() == checkpointMask);
    testAssert(replay.results.size() == 3);
    testAssert(!replay.results[0].atomicStateSnapshot.has_value());
    testAssert(!replay.results[1].atomicStateSnapshot.has_value());

    const CollapseGoApplyResult& trigger = replay.results[2];
    testAssert(trigger.settlementTriggered);
    testAssert(trigger.settlementReason == CollapseGoSettlementReason::PRE_THRESHOLD_TWO_PASSES);
    testAssert(trigger.atomicStateSnapshot.has_value());
    testAssert(trigger.atomicStateSnapshot->getAtomicActionCount() == 6);
    testAssert(trigger.atomicStateSnapshot->getConsecutivePasses() == 2);
    testAssert(trigger.atomicStateSnapshot->getPhase() == CollapseGoPhase::COLLAPSE_PLAY);
    testAssert(trigger.atomicStateSnapshot->getActor() == P_WHITE);
    testAssert(trigger.capturedStones.empty());
    testAssert(!trigger.terminalEvent.has_value());
    testAssert(!trigger.terminalScoreEventEmitted);
    testAssert(trigger.positionalSuperkoAppends == 4);
    testAssert(trigger.settlementSteps.size() == 3);
    const int64_t expectedOrigins[3] = {3,2,1};
    const Player expectedOwners[3] = {P_BLACK,P_WHITE,P_BLACK};
    const GameActionKind expectedKinds[3] = {
      GameActionKind::DOUBLE_START,
      GameActionKind::EIGHTWAY,
      GameActionKind::IMMORTAL,
    };
    const int expectedSources[3] = {1,80,0};
    const bool expectedNoOp[3] = {true,false,false};
    for(size_t index = 0; index < trigger.settlementSteps.size(); index++) {
      const CollapseGoSettlementStep& step = trigger.settlementSteps[index];
      testAssert(step.stepIndex == static_cast<int64_t>(index));
      testAssert(step.originActionNumber == expectedOrigins[index]);
      testAssert(step.owner == expectedOwners[index]);
      testAssert(step.originKind == expectedKinds[index]);
      testAssert(step.sourcePoint == expectedSources[index]);
      testAssert(step.noOp == expectedNoOp[index]);
      testAssert(step.abilityDeactivated != expectedNoOp[index]);
      testAssert(step.removalBatches.empty());
      testAssert(step.positionalSuperkoHistoryIndex == static_cast<int64_t>(7 + index));
    }

    const CollapseGoState& finalState = replay.finalState;
    testAssert(finalState.getAtomicActionCount() == 6);
    testAssert(finalState.getRevision() == 6);
    testAssert(finalState.getLogPosition() == 9);
    testAssert(finalState.getSettledLedgerCount() == 3);
    testAssert(finalState.getStableTerminalEventCount() == 0);
    testAssert(finalState.getPositionalSuperkoHistory().size() == 10);
    testAssert(finalState.getPhase() == CollapseGoPhase::ORDINARY_PLAY);
    testAssert(finalState.getActor() == P_WHITE);
    testAssert(finalState.isSettlementCompleted());
    testAssert(!finalState.getPendingDouble().has_value());
    testAssert(!finalState.getTerminalState().has_value());
    testAssert(replay.legalMasks.back().count() == 78);
    for(Player player: {P_BLACK,P_WHITE}) {
      for(CollapseGoAbility ability: {
        CollapseGoAbility::IMMORTAL,
        CollapseGoAbility::DOUBLE_MOVE,
        CollapseGoAbility::EIGHTWAY,
      }) {
        testAssert(finalState.getInitialQuota(player,ability) == 1);
        testAssert(finalState.getRemainingQuota(player,ability) == 0);
      }
    }
    testAssert(finalState.getUsedQuota(P_BLACK,CollapseGoAbility::IMMORTAL) == 1);
    testAssert(finalState.getUsedQuota(P_BLACK,CollapseGoAbility::DOUBLE_MOVE) == 1);
    testAssert(finalState.getUsedQuota(P_BLACK,CollapseGoAbility::EIGHTWAY) == 0);
    testAssert(finalState.getExpiredQuota(P_BLACK,CollapseGoAbility::IMMORTAL) == 0);
    testAssert(finalState.getExpiredQuota(P_BLACK,CollapseGoAbility::DOUBLE_MOVE) == 0);
    testAssert(finalState.getExpiredQuota(P_BLACK,CollapseGoAbility::EIGHTWAY) == 1);
    testAssert(finalState.getUsedQuota(P_WHITE,CollapseGoAbility::IMMORTAL) == 0);
    testAssert(finalState.getUsedQuota(P_WHITE,CollapseGoAbility::DOUBLE_MOVE) == 0);
    testAssert(finalState.getUsedQuota(P_WHITE,CollapseGoAbility::EIGHTWAY) == 1);
    testAssert(finalState.getExpiredQuota(P_WHITE,CollapseGoAbility::IMMORTAL) == 1);
    testAssert(finalState.getExpiredQuota(P_WHITE,CollapseGoAbility::DOUBLE_MOVE) == 1);
    testAssert(finalState.getExpiredQuota(P_WHITE,CollapseGoAbility::EIGHTWAY) == 0);
    finalState.checkConsistency();
  }

  // A post-settlement checkpoint preserves a Double source until its later exact capture and score.
  {
    const int boardSize = 9;
    const vector<CollapseGoReplayStep> prefix = {
      {P_BLACK,specialAction(GameActionKind::DOUBLE_START,boardSize,0,0)},
      {P_BLACK,normalAction(boardSize,8,8)},
      {P_WHITE,GameAction::pass()},
      {P_BLACK,GameAction::pass()},
    };
    const vector<CollapseGoReplayStep> suffix = {
      {P_WHITE,normalAction(boardSize,1,0)},
      {P_BLACK,normalAction(boardSize,4,4)},
      {P_WHITE,normalAction(boardSize,0,1)},
      {P_BLACK,GameAction::pass()},
      {P_WHITE,GameAction::pass()},
    };

    CollapseGoState checkpoint(CollapseGoConfig::allOne(boardSize));
    for(const CollapseGoReplayStep& step: prefix)
      applyAccepted(checkpoint,step.first,step.second);
    checkpoint.checkConsistency();
    testAssert(checkpoint.getAtomicActionCount() == 4);
    testAssert(checkpoint.getRevision() == 4);
    testAssert(checkpoint.getLogPosition() == 5);
    testAssert(checkpoint.getSettledLedgerCount() == 1);
    testAssert(checkpoint.getStableTerminalEventCount() == 0);
    testAssert(checkpoint.getPositionalSuperkoHistory().size() == 6);
    testAssert(checkpoint.getPhase() == CollapseGoPhase::ORDINARY_PLAY);
    testAssert(checkpoint.getActor() == P_WHITE);
    testAssert(checkpoint.isSettlementCompleted());
    testAssert(checkpoint.getLedger().size() == 1);
    const CollapseGoLedgerEntry& checkpointEntry = checkpoint.getLedger().at(0);
    testAssert(checkpointEntry.specialLink == 1);
    testAssert(checkpointEntry.originActionNumber == 1);
    testAssert(checkpointEntry.owner == P_BLACK);
    testAssert(checkpointEntry.originKind == GameActionKind::DOUBLE_START);
    testAssert(checkpointEntry.sourcePoint == 0);
    testAssert(checkpointEntry.abilityState == CollapseGoLedgerAbilityState::INACTIVE);
    testAssert(checkpointEntry.stoneState == CollapseGoLedgerStoneState::ON_BOARD);
    testAssert(checkpointEntry.settlementState == CollapseGoLedgerSettlementState::SETTLED);
    testAssert(checkpointEntry.tombstone);
    const CollapseGoCell& checkpointSourceCell = checkpoint.getPosition().getCell(0);
    testAssert(checkpointSourceCell.getColor() == C_BLACK);
    const CollapseGoStoneSource checkpointSource = checkpointSourceCell.getSource();
    testAssert(checkpointSource.originActionNumber == 1);
    testAssert(checkpointSource.originKind == GameActionKind::DOUBLE_START);
    testAssert(checkpointSource.specialLink.has_value());
    testAssert(*checkpointSource.specialLink == 1);
    CollapseGoLegalMask checkpointMask = deriveStableReplayMask(checkpoint);
    testAssert(checkpointMask.count() == 80);
    testAssert(checkpointMask.test(static_cast<size_t>(actionIdAt(
      GameActionKind::NORMAL,boardSize,1,0
    ))));
    testAssert(checkpointMask.test(static_cast<size_t>(GameAction::PASS_ACTION_ID)));

    CollapseGoState immutableCheckpoint(checkpoint);
    CollapseGoSuffixRecord replay = assertDeterministicSuffixReplay(checkpoint,prefix,suffix);
    testAssert(checkpoint.isEqualForTesting(immutableCheckpoint));
    testAssert(replay.legalMasks.front() == checkpointMask);
    testAssert(replay.results.size() == 5);
    testAssert(replay.statesAfterActions[0].getPosition().getCell(0).getSource() == checkpointSource);
    testAssert(replay.statesAfterActions[1].getPosition().getCell(0).getSource() == checkpointSource);

    const CollapseGoApplyResult& capture = replay.results[2];
    testAssert(capture.capturedStones == vector<Loc>({Location::getLoc(0,0,boardSize)}));
    testAssert(!capture.atomicStateSnapshot.has_value());
    testAssert(!capture.settlementTriggered);
    testAssert(capture.settlementSteps.empty());
    testAssert(!capture.terminalEvent.has_value());
    testAssert(capture.positionalSuperkoAppends == 1);
    const CollapseGoState& afterCapture = replay.statesAfterActions[2];
    testAssert(afterCapture.getPosition().isEmpty(0));
    testAssert(afterCapture.getAtomicActionCount() == 7);
    testAssert(afterCapture.getRevision() == 7);
    testAssert(afterCapture.getLogPosition() == 8);
    testAssert(afterCapture.getSettledLedgerCount() == 1);
    testAssert(afterCapture.getPositionalSuperkoHistory().size() == 9);
    const CollapseGoLedgerEntry& capturedEntry = afterCapture.getLedger().at(0);
    testAssert(capturedEntry.specialLink == checkpointEntry.specialLink);
    testAssert(capturedEntry.originActionNumber == checkpointEntry.originActionNumber);
    testAssert(capturedEntry.owner == checkpointEntry.owner);
    testAssert(capturedEntry.originKind == checkpointEntry.originKind);
    testAssert(capturedEntry.sourcePoint == checkpointEntry.sourcePoint);
    testAssert(capturedEntry.abilityState == CollapseGoLedgerAbilityState::INACTIVE);
    testAssert(capturedEntry.stoneState == CollapseGoLedgerStoneState::CAPTURED);
    testAssert(capturedEntry.settlementState == CollapseGoLedgerSettlementState::SETTLED);
    testAssert(capturedEntry.tombstone);

    const CollapseGoApplyResult& terminal = replay.results[4];
    testAssert(terminal.capturedStones.empty());
    testAssert(terminal.atomicStateSnapshot.has_value());
    testAssert(terminal.atomicStateSnapshot->getAtomicActionCount() == 9);
    testAssert(terminal.atomicStateSnapshot->getRevision() == 9);
    testAssert(terminal.atomicStateSnapshot->getLogPosition() == 10);
    testAssert(terminal.atomicStateSnapshot->getPhase() == CollapseGoPhase::ORDINARY_PLAY);
    testAssert(terminal.atomicStateSnapshot->getConsecutivePasses() == 2);
    testAssert(!terminal.settlementTriggered);
    testAssert(terminal.settlementSteps.empty());
    testAssert(terminal.terminalScoreEventEmitted);
    testAssert(terminal.terminalEvent.has_value());
    testAssert(terminal.terminalEvent->reason == CollapseGoTerminalReason::SCORE);
    testAssert(terminal.terminalEvent->positionalSuperkoHistoryIndex == 11);
    testAssert(terminal.terminalEvent->revision == 9);
    testAssert(terminal.terminalEvent->logPosition == 11);
    testAssert(terminal.positionalSuperkoAppends == 2);

    const CollapseGoState& finalState = replay.finalState;
    testAssert(finalState.getAtomicActionCount() == 9);
    testAssert(finalState.getRevision() == 9);
    testAssert(finalState.getLogPosition() == 11);
    testAssert(finalState.getSettledLedgerCount() == 1);
    testAssert(finalState.getStableTerminalEventCount() == 1);
    testAssert(finalState.getPositionalSuperkoHistory().size() == 12);
    testAssert(finalState.getPhase() == CollapseGoPhase::TERMINAL);
    testAssert(finalState.getActor() == C_EMPTY);
    testAssert(finalState.isSettlementCompleted());
    testAssert(finalState.getTerminalState().has_value());
    testAssert(finalState.getTerminalState()->reason == CollapseGoTerminalReason::SCORE);
    testAssert(replay.legalMasks.back().none());
    const CollapseGoLedgerEntry& finalEntry = finalState.getLedger().at(0);
    testAssert(finalEntry == capturedEntry);
    for(Player player: {P_BLACK,P_WHITE}) {
      for(CollapseGoAbility ability: {
        CollapseGoAbility::IMMORTAL,
        CollapseGoAbility::DOUBLE_MOVE,
        CollapseGoAbility::EIGHTWAY,
      }) {
        testAssert(finalState.getInitialQuota(player,ability) == 1);
        testAssert(finalState.getRemainingQuota(player,ability) == 0);
      }
    }
    testAssert(finalState.getUsedQuota(P_BLACK,CollapseGoAbility::IMMORTAL) == 0);
    testAssert(finalState.getUsedQuota(P_BLACK,CollapseGoAbility::DOUBLE_MOVE) == 1);
    testAssert(finalState.getUsedQuota(P_BLACK,CollapseGoAbility::EIGHTWAY) == 0);
    testAssert(finalState.getExpiredQuota(P_BLACK,CollapseGoAbility::IMMORTAL) == 1);
    testAssert(finalState.getExpiredQuota(P_BLACK,CollapseGoAbility::DOUBLE_MOVE) == 0);
    testAssert(finalState.getExpiredQuota(P_BLACK,CollapseGoAbility::EIGHTWAY) == 1);
    testAssert(finalState.getUsedQuota(P_WHITE,CollapseGoAbility::IMMORTAL) == 0);
    testAssert(finalState.getUsedQuota(P_WHITE,CollapseGoAbility::DOUBLE_MOVE) == 0);
    testAssert(finalState.getUsedQuota(P_WHITE,CollapseGoAbility::EIGHTWAY) == 0);
    testAssert(finalState.getExpiredQuota(P_WHITE,CollapseGoAbility::IMMORTAL) == 1);
    testAssert(finalState.getExpiredQuota(P_WHITE,CollapseGoAbility::DOUBLE_MOVE) == 1);
    testAssert(finalState.getExpiredQuota(P_WHITE,CollapseGoAbility::EIGHTWAY) == 1);
    finalState.checkConsistency();
  }

  // Copy-then-commit preserves the original exact state while the copy advances independently.
  {
    CollapseGoState original(CollapseGoConfig::allOne(9));
    CollapseGoState committed(original);
    CollapseGoApplyResult result = playNormal(committed,4,4);
    testAssert(result.accepted);
    testAssert(original.getPosition().isEmpty(4,4));
    testAssert(original.getAtomicActionCount() == 0);
    testAssert(original.getRevision() == 0);
    testAssert(original.getLogPosition() == 0);
    testAssert(committed.getPosition().getColor(4,4) == C_BLACK);
    testAssert(committed.getPosition().getCell(4,4).getSource().originActionNumber == 1);
    testAssert(committed.getAtomicActionCount() == 1);
    testAssert(committed.getRevision() == 1);
    testAssert(committed.getLogPosition() == 1);
    testAssert(!original.isEqualForTesting(committed));
    original.checkConsistency();
    committed.checkConsistency();

    CollapseGoState administrativeOriginal(CollapseGoConfig::allOne(9));
    playNormal(administrativeOriginal,4,4);
    CollapseGoState administrativeCommitted(administrativeOriginal);
    CollapseGoApplyResult termination = terminateAccepted(
      administrativeCommitted,P_BLACK,CollapseGoAdministrativeTerminationReason::RESIGNATION
    );
    testAssert(termination.terminalEvent.has_value());
    testAssert(!administrativeOriginal.getTerminalState().has_value());
    testAssert(administrativeOriginal.getPhase() == CollapseGoPhase::COLLAPSE_PLAY);
    testAssert(administrativeOriginal.getActor() == P_WHITE);
    testAssert(administrativeOriginal.getRevision() == 1);
    testAssert(administrativeCommitted.getTerminalState().has_value());
    testAssert(administrativeCommitted.getRevision() == 2);
    testAssert(!administrativeOriginal.isEqualForTesting(administrativeCommitted));

    CollapseGoState copiedTerminal(administrativeCommitted);
    testAssert(copiedTerminal.isEqualForTesting(administrativeCommitted));
    CollapseGoState assignedTerminal(CollapseGoConfig::allZero(13));
    assignedTerminal = administrativeCommitted;
    testAssert(assignedTerminal.isEqualForTesting(administrativeCommitted));
    administrativeOriginal.checkConsistency();
    administrativeCommitted.checkConsistency();
    copiedTerminal.checkConsistency();
    assignedTerminal.checkConsistency();
  }
}
