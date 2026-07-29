#ifndef GAME_COLLAPSEGOTOPOLOGY_H_
#define GAME_COLLAPSEGOTOPOLOGY_H_

#include <vector>

#include "../game/collapsegoposition.h"

struct CollapseGoGroup {
  Color color;
  std::vector<int> stones;
  std::vector<int> liberties;

  CollapseGoGroup();

  bool operator==(const CollapseGoGroup& other) const;
  bool operator!=(const CollapseGoGroup& other) const;
};

class CollapseGoTopology {
public:
  // Increment 0 deliberately scans only ordinary orthogonal connectivity.
  // A future mixed-interface scanner can be added without changing the exact
  // position or the deterministic result representation.
  static CollapseGoTopology fullScanN4(const CollapseGoPosition& position);

  const std::vector<CollapseGoGroup>& getGroups() const;
  int getGroupIndexAt(int point) const;
  const CollapseGoGroup& getGroupAt(int point) const;

  void checkConsistency(const CollapseGoPosition& position) const;

private:
  int boardSize;
  std::vector<CollapseGoGroup> groups;
  std::vector<int> groupIndexByPoint;

  explicit CollapseGoTopology(int topologyBoardSize);
};

#endif // GAME_COLLAPSEGOTOPOLOGY_H_
