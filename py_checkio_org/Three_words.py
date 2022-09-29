def checkio(words: str) -> bool:
    counter = 0
    for i_word in words.split():
        if i_word.isalpha():
            counter += 1
            if counter >= 3:
                return True
        else:
            counter = 0
    if counter < 3:
        return False


print("Example:")
print(checkio("Hello World hello"))

assert checkio("Hello World hello") == True
assert checkio("He is 123 man") == False
assert checkio("1 2 3 4") == False
assert checkio("bla bla bla bla") == True
assert checkio("Hi") == False

print("The mission is done! Click 'Check Solution' to earn rewards!")
