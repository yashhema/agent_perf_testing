"""Generate 100 text files with novel-like content for testing."""

import os
import random

# Sample paragraphs to combine into novels
PARAGRAPHS = [
    """The morning sun cast long shadows across the valley as Sarah made her way down the winding path. She had walked this route countless times before, but today felt different. The air carried a strange stillness, as if the world itself was holding its breath in anticipation of something momentous.""",

    """In the distance, the ancient castle stood atop the hill, its weathered stones telling stories of centuries past. The villagers rarely spoke of what lay within those walls, preferring to keep their children away with whispered tales of ghosts and curses. But Sarah had never been one to believe in superstitions.""",

    """The marketplace was bustling with activity when Thomas arrived. Merchants called out their wares, children darted between the stalls, and the smell of fresh bread mingled with exotic spices from distant lands. He pulled his coat tighter against the autumn chill and searched the crowd for a familiar face.""",

    """Dr. Elizabeth Chen stared at the data on her screen, unable to believe what she was seeing. After fifteen years of research, countless failed experiments, and nights spent sleeping in her laboratory, the breakthrough had finally come. The implications were staggering.""",

    """The ship creaked and groaned as another wave crashed against its hull. Captain Morrison gripped the wheel with white-knuckled determination, shouting orders that were lost in the howling wind. They had survived storms before, but nothing like this tempest that seemed determined to drag them to the ocean floor.""",

    """Memory is a peculiar thing, James thought as he sorted through the old photographs. Some moments remain crystal clear decades later, while others fade like morning mist. He picked up a faded image of a woman with kind eyes and felt the familiar ache of loss.""",

    """The detective examined the crime scene with practiced efficiency. Every detail mattered - the position of the furniture, the half-empty coffee cup, the window left slightly ajar. Somewhere in this room lay the answer to who had committed this terrible act.""",

    """Professor Williams stood before the lecture hall, chalk in hand, facing a sea of skeptical undergraduate faces. Quantum mechanics was never an easy subject to teach, but she had learned that the key was making the impossible seem merely improbable.""",

    """The forest stretched endlessly in every direction, ancient trees forming a canopy so thick that only scattered beams of light reached the forest floor. Marcus checked his compass again, though he knew it would be useless here. Something about this place defied normal navigation.""",

    """In the kitchen of the small apartment, Maria prepared her grandmother's recipe with careful attention. Each ingredient held a memory - the oregano from the garden back home, the olive oil her father had pressed himself, the tomatoes ripened under the Mediterranean sun.""",

    """The courtroom fell silent as the defendant rose to speak. After months of testimony and evidence, this was the moment everyone had been waiting for. Would he finally reveal the truth that had eluded investigators for so long?""",

    """Technology had changed everything, but some things remained constant. Despite all the advances of the 22nd century, people still fell in love, still experienced heartbreak, still searched for meaning in an indifferent universe. Alex stared out at the colony ships departing for distant stars and wondered if humanity would ever truly change.""",

    """The old bookshop on Chestnut Street had been there for as long as anyone could remember. Its shelves sagged under the weight of countless volumes, and dust motes danced in the light filtering through grimy windows. To the casual observer, it was merely a relic of a bygone era.""",

    """War had taken everything from him - his home, his family, his faith in humanity. Now, standing in the ruins of what had once been a thriving city, Colonel Peterson wondered if anything could ever be rebuilt from such devastation.""",

    """The recipe called for patience, something Rachel had never possessed in abundance. But bread-making demanded it, and she was determined to master this ancient art. As she kneaded the dough, she found her thoughts wandering to conversations left unfinished.""",

    """Music filled the concert hall, each note a thread in the tapestry of sound the orchestra wove together. In the front row, a young girl closed her eyes and let the melody transport her to places she had only imagined in dreams.""",

    """The laboratory was quiet at this hour, the usual bustle of researchers replaced by the hum of equipment and the soft glow of computer monitors. Dr. Patel preferred working at night when she could think without interruption.""",

    """Letters had arrived every week for forty years, tied with blue ribbon and stored in the cedar chest at the foot of her bed. Now, with trembling hands, Eleanor untied the last bundle and began to read words written by a man she had loved and lost.""",

    """The climb was more treacherous than the map had suggested. With each step, loose rocks threatened to send him tumbling down the mountainside. But the view from the summit, according to those who had made it, was worth every moment of danger.""",

    """In the garden behind the cottage, herbs grew in wild abundance. Rosemary, thyme, lavender, and sage formed a fragrant tapestry that attracted bees and butterflies throughout the summer months. Here, far from the noise of the city, one could almost forget the troubles of the modern world.""",
]

CHAPTER_TITLES = [
    "The Beginning", "Shadows and Light", "The Journey", "Unexpected Encounters",
    "Revelations", "The Storm", "Memories", "Crossroads", "The Truth",
    "Consequences", "Hope", "The Decision", "Aftermath", "New Horizons",
    "The Return", "Secrets", "Forgiveness", "The Challenge", "Resolution",
    "Epilogue"
]

CHARACTER_NAMES = [
    "Sarah", "Thomas", "Elizabeth", "James", "Maria", "Marcus", "Rachel",
    "William", "Catherine", "Alexander", "Emily", "Robert", "Victoria",
    "Michael", "Margaret", "David", "Anne", "Christopher", "Helen", "Daniel"
]

DIALOGUE_TEMPLATES = [
    '"{name} said, looking out the window.",',
    '"I never expected this," {name} replied quietly.',
    '"{name} paused before answering, considering the implications.',
    '"We have to try," {name} insisted. "There is no other choice."',
    '"Tell me everything," {name} demanded. "I need to understand."',
    '"It was not supposed to happen this way," {name} whispered.',
    '"{name} shook their head slowly. "You do not understand."',
    '"Perhaps," {name} conceded, "but we must consider the alternatives."',
    '"I remember," {name} said softly, "when things were different."',
    '"The truth is rarely simple," {name} observed.',
]

def generate_paragraph():
    """Generate a random paragraph."""
    return random.choice(PARAGRAPHS)

def generate_dialogue():
    """Generate a line of dialogue."""
    template = random.choice(DIALOGUE_TEMPLATES)
    name = random.choice(CHARACTER_NAMES)
    return template.format(name=name)

def generate_chapter(chapter_num):
    """Generate a chapter with 10-20 paragraphs."""
    title = random.choice(CHAPTER_TITLES)
    content = [f"\nChapter {chapter_num}: {title}\n"]
    content.append("=" * 40 + "\n")

    num_paragraphs = random.randint(10, 20)
    for _ in range(num_paragraphs):
        if random.random() < 0.3:  # 30% chance of dialogue
            content.append(generate_dialogue())
        else:
            content.append(generate_paragraph())
        content.append("\n\n")

    return "".join(content)

def generate_novel(novel_num):
    """Generate a complete novel with 5-10 chapters."""
    title = f"Novel {novel_num:03d}: {random.choice(['The', 'A', 'Beyond', 'Before', 'After'])} " \
            f"{random.choice(['Shadow', 'Light', 'Journey', 'Secret', 'Promise', 'Dream', 'Memory', 'Storm', 'Legacy', 'Quest'])}"

    content = [title]
    content.append("\n" + "=" * 50 + "\n\n")
    content.append(f"By Anonymous Author\n\n")
    content.append("This is a work of fiction. Any resemblance to actual persons, ")
    content.append("living or dead, or actual events is purely coincidental.\n\n")
    content.append("=" * 50 + "\n")

    num_chapters = random.randint(5, 10)
    for chapter_num in range(1, num_chapters + 1):
        content.append(generate_chapter(chapter_num))

    content.append("\n\nTHE END\n")
    return "".join(content)

def main():
    output_dir = os.path.dirname(os.path.abspath(__file__))
    normal_dir = os.path.join(output_dir, "normal")

    os.makedirs(normal_dir, exist_ok=True)

    print("Generating 100 novels...")
    for i in range(1, 101):
        novel_content = generate_novel(i)
        filename = os.path.join(normal_dir, f"novel_{i:03d}.txt")
        with open(filename, "w", encoding="utf-8") as f:
            f.write(novel_content)

        if i % 10 == 0:
            print(f"  Generated {i}/100 novels")

    print(f"\nDone! 100 novels created in: {normal_dir}")

    # Print stats
    total_size = sum(
        os.path.getsize(os.path.join(normal_dir, f))
        for f in os.listdir(normal_dir)
        if f.endswith('.txt')
    )
    print(f"Total size: {total_size / 1024 / 1024:.2f} MB")

if __name__ == "__main__":
    main()
