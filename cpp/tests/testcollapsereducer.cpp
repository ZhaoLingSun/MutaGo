#include "../tests/tests.h"

#include <algorithm>
#include <limits>

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

CollapseGoApplyResult playDoubleStart(CollapseGoState& state, int x, int y) {
  return applyAccepted(
    state,
    state.getActor(),
    specialAction(GameActionKind::DOUBLE_START,state.getConfig().getBoardSize(),x,y)
  );
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

  const PositionalSuperkoHistory& referenceHistory = reference.getPositionalSuperkoHistory();
  const PositionalSuperkoHistory& transformedHistory = transformed.getPositionalSuperkoHistory();
  testAssert(transformedHistory.size() == referenceHistory.size());
  for(size_t index = 0; index < referenceHistory.size(); index++) {
    testAssert(transformedHistory.at(index).getOccupancy() == transformedOccupancy(
      referenceHistory.at(index).getOccupancy(),boardSize,symmetry
    ));
  }

  CollapseGoTopology referenceTopology = CollapseGoTopology::fullScanN4(
    reference.getPosition(),reference.getArmedImmortalAnchors()
  );
  CollapseGoTopology transformedTopology = CollapseGoTopology::fullScanN4(
    transformed.getPosition(),transformed.getArmedImmortalAnchors()
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

}

void Tests::runCollapseReducerTests() {
  cout << "Running Collapse Go reducer slice tests" << endl;

  // Configuration, thresholds, and exact initial PSK seeding.
  {
    testAssert(CollapseGoConfig::thresholdForBoardSize(9) == 34);
    testAssert(CollapseGoConfig::thresholdForBoardSize(13) == 70);
    testAssert(CollapseGoConfig::thresholdForBoardSize(19) == 150);
    expectStringError([]() { CollapseGoConfig::allZero(11); });
    expectStringError([]() {
      CollapseGoLedgerEntry(1,1,P_BLACK,GameActionKind::EIGHTWAY,0);
    });
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

  // Double rejects ordinary suicide, while a newly armed Immortal survives the same zero-liberty point.
  {
    CollapseGoState state(CollapseGoConfig::allOne(9));
    playNormal(state,8,8); playNormal(state,1,2);
    playNormal(state,8,7); playNormal(state,3,2);
    playNormal(state,7,8); playNormal(state,2,1);
    playNormal(state,7,7); playNormal(state,2,3);
    expectRejectedAtomically(
      state,
      P_BLACK,
      specialAction(GameActionKind::DOUBLE_START,9,2,2),
      CollapseGoApplyError::SUICIDE,
      true
    );
    expectRejectedAtomically(
      state,P_BLACK,specialAction(GameActionKind::EIGHTWAY,9,2,2),
      CollapseGoApplyError::UNSUPPORTED_BY_SLICE,false
    );
    playImmortal(state,2,2);
    CollapseGoTopology topology = CollapseGoTopology::fullScanN4(
      state.getPosition(),state.getArmedImmortalAnchors()
    );
    const CollapseGoGroup& protectedGroup = topology.getGroupAt(2 + 2 * 9);
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

  // Exhausted specials are semantic rejections; Eightway remains explicitly unsupported by the N4 slice.
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

    CollapseGoState unsupported(CollapseGoConfig::allOne(9));
    expectRejectedAtomically(
      unsupported,P_BLACK,specialAction(GameActionKind::EIGHTWAY,9,4,4),
      CollapseGoApplyError::UNSUPPORTED_BY_SLICE,false
    );
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
    testAssert(state.getLedger().empty());
    testAssert(state.getRemainingQuota(P_WHITE,CollapseGoAbility::IMMORTAL) == 1);
    testAssert(state.getUsedQuota(P_WHITE,CollapseGoAbility::IMMORTAL) == 0);
    expectRejectedAtomically(
      state,P_WHITE,specialAction(GameActionKind::EIGHTWAY,9,2,2),
      CollapseGoApplyError::UNSUPPORTED_BY_SLICE,false
    );
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

  // Malformed restored shells cannot forge armed anchors or live Immortal tombstones.
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
  }
}
