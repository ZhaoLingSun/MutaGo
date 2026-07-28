#ifndef GAME_POSITIONALSUPERKO_H_
#define GAME_POSITIONALSUPERKO_H_

#include <cstdint>
#include <vector>

#include "../game/board.h"

class PositionalSuperkoKey {
public:
  explicit PositionalSuperkoKey(const Board& board);

  int getXSize() const;
  int getYSize() const;
  const std::vector<uint8_t>& getOccupancy() const;

  bool operator==(const PositionalSuperkoKey& other) const;
  bool operator!=(const PositionalSuperkoKey& other) const;

private:
  int xSize;
  int ySize;
  std::vector<uint8_t> occupancy;
};

class PositionalSuperkoHistory {
public:
  explicit PositionalSuperkoHistory(const Board& initialBoard);

  size_t size() const;
  const PositionalSuperkoKey& at(size_t index) const;
  const PositionalSuperkoKey& back() const;
  bool contains(const PositionalSuperkoKey& key) const;
  bool contains(const Board& board) const;
  void append(const PositionalSuperkoKey& key);
  void append(const Board& board);

  bool operator==(const PositionalSuperkoHistory& other) const;
  bool operator!=(const PositionalSuperkoHistory& other) const;

private:
  std::vector<PositionalSuperkoKey> entries;
};

#endif // GAME_POSITIONALSUPERKO_H_
