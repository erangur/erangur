import cards


from enum import Enum

class Action(Enum):
    STAND = 'stand'
    HIT = 'hit'
    DOUBLE = 'double'
    SPLIT = 'split'

class Hand():
    def __init__(self, hand, is_split=False):
        self.hand = hand
        self.is_doubled = False
        self.is_active = True
        self.is_split = is_split

    def get_choices(self):
        choices = [Action.STAND, Action.HIT]
        if self._is_doublable():
            choices.append(Action.DOUBLE)
        if self._is_splittable():
            choices.append(Action.SPLIT)
        return choices
    
    def get_state(self):
       return (self.get_hand_value(), self._is_soft(), self._is_splittable(), self.is_doubled, self.is_active)

    def get_hand_value(self):
        value = cards.calculate_hand(self.hand)
        return 22 if value > 21 else value

    def is_blackjack(self):
        return self.get_hand_value() == 21 and len(self.hand) == 2 and not self.is_split
    
    def is_doubled(self):
        return self.is_doubled

    def hit(self):
        self.hand.append(cards.random_card())
        if cards.calculate_hand(self.hand) > 21:
            self.is_active = False

    def stand(self):
        self.is_active = False

    def double(self):
        self.hit()
        self.is_doubled = True
        self.is_active = False

    def split(self):
        return [Hand([self.hand[0]], is_split=True), Hand([self.hand[1]], is_split=True)]

    def _is_soft(self):
        return cards.is_soft(self.hand)
    
    def _is_splittable(self):
        return len(self.hand) == 2 and self.hand[0] == self.hand[1] and not self.is_split
    
    def _is_doublable(self):
        return len(self.hand) == 2 and not self.is_split


def random_hand():
    return Hand([cards.random_card(), cards.random_card()])

