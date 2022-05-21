from random import shuffle
from random import choice


class Cards:

    def __init__(self, suit, value):
        self.suit = suit
        self.value = value

    def __str__(self):
        return '{cards_value} {cards_suit}'.format(cards_value=self.value,
                                                   cards_suit=self.suit
                                                   )


class Deck:

    def __init__(self):
        self.cards = [Cards(i_suit, i_value) for i_suit in ['Diamonds', 'Hearts', 'Clubs', 'Spades']
                      for i_value in ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A'
                                      ]
                      ]

    def shuffle(self):
        if len(self.cards) > 1:
            shuffle(self.cards)

    def deal_cards(self):
        if len(self.cards) > 1:
            cards = self.cards.pop(self.cards.index(choice(self.cards)))

            return cards


class Hand:

    def __init__(self, dealer=False):
        self.dealer = dealer
        self.cards = list()
        self.value = 0

    def add_card(self, card):
        self.cards.append(card)

    def calculate_value(self):
        ace = False
        self.value = 0
        for i_cards in self.cards:
            if i_cards.value.isdigit():
                self.value += int(i_cards.value)
            else:
                if i_cards.value != 'A':
                    self.value += 10
                else:
                    ace = True
                    self.value += 11
            if ace is True and self.value > 21:
                quantity_of_aces = self.cards.count('A')
                self.value -= (10 * quantity_of_aces)

    def get_value(self):
        self.calculate_value()
        return self.value

    def output_hand(self):
        if self.dealer:
            print('hidden')
            for card in self.cards[1::]:
                print(card)
            print()
        else:
            for card in self.cards:
                print(card)
            print('Value: {}'.format(self.get_value()))


class Game:

    def __init__(self):
        pass

    def check_for_21(self):
        player = False
        dealer = False

        if self.player_hand.get_value() == 21:
            player = True

        if self.dealer_hand.get_value() == 21:
            dealer = True

        return player, dealer

    def check_for_blackjack(self):
        player = False
        dealer = False

        if self.player_hand.get_value() == 21:
            player = True

        if self.dealer_hand.get_value() == 21:
            dealer = True

        return player, dealer

    def show_21_result(self, player_has_21, dealer_has_21):
        if player_has_21 and dealer_has_21:
            print('Both players have 21! Draw!')
        elif player_has_21:
            print('You have 21! You Win!')
        elif dealer_has_21:
            print('Dealer has 21! Dealer wins!')

    def show_blackjack_result(self, player_has_blackjack, dealer_has_blackjack):
        if player_has_blackjack and dealer_has_blackjack:
            print('Both players have BlackJack! Draw!')
        elif player_has_blackjack:
            print('You have BlackJack! You Win!')
        elif dealer_has_blackjack:
            print('Dealer has BlackJack! Dealer wins!')

    def dealer_is_over(self):
        return self.dealer_hand.get_value() > 21

    def player_is_over(self):
        return self.player_hand.get_value() > 21

    def play(self):
        play = True

        while play:
            self.deck = Deck()
            self.deck.shuffle()

            self.player_hand = Hand()
            self.dealer_hand = Hand(dealer=True)

            for i_deal in range(2):
                self.player_hand.add_card(self.deck.deal_cards())
                self.dealer_hand.add_card(self.deck.deal_cards())

            print('Your hand is:')
            self.player_hand.output_hand()
            print()
            print("Dealer's hand:")
            self.dealer_hand.output_hand()

            game_over = False
            while not game_over:
                if len(self.player_hand.cards) < 3 and len(self.dealer_hand.cards) < 3:
                    player_has_blackjack, dealer_has_blackjack = self.check_for_blackjack()
                    if player_has_blackjack or dealer_has_blackjack:
                        game_over = True
                        self.show_blackjack_result(player_has_blackjack, dealer_has_blackjack)
                        continue
                else:
                    player_has_21, dealer_has_21 = self.check_for_21()
                    if player_has_21 or dealer_has_21:
                        game_over = True
                        self.show_21_result(player_has_21, dealer_has_21)
                        continue

                select_action = input('\nSelect next / stop: ').strip().lower()
                while select_action not in ['next', 'stop', 'n', 's']:
                    select_action = input('Please enter next / stop: ')

                if select_action in ['n', 'next']:
                    self.player_hand.add_card(self.deck.deal_cards())
                    self.player_hand.output_hand()

                    if self.player_is_over():
                        print("You have lost!")
                        game_over = True
                else:
                    player_hand_value = self.player_hand.get_value()
                    dealer_hand_value = self.dealer_hand.get_value()

                    while dealer_hand_value < 17:
                        self.dealer_hand.add_card(self.deck.deal_cards())
                        self.dealer_hand.output_hand()
                        dealer_hand_value = self.dealer_hand.get_value()

                    if self.dealer_is_over():
                        print("You win! Deler's result: {}".format(self.dealer_hand.get_value()))
                        game_over = True
                        continue

                    print('\nFinal Results')
                    print('Your hand:', player_hand_value)
                    print("Dealer's hand:", dealer_hand_value)

                    if player_hand_value > dealer_hand_value:
                        print('You Win!')
                    elif player_hand_value == dealer_hand_value:
                        print('Tie!')
                    else:
                        print('Dealer Wins!')
                    game_over = True

            again = input('\nPlay Again? yes / no: ').strip().lower()
            while again not in ['yes', 'no', 'y', 'n']:
                again = input('Play Again? yes / no').strip().lower()
            if again in ['no', 'n']:
                print("Thanks for playing!")
                play = False
            else:
                game_over = False
