import os

# The tests use the stand-in translator, which tags what it translates ("[wo] ..."): they run with a reply language that
# is translated (the real default, wo, speaks the agent's text as it is). Set before waxal_agent is imported.
os.environ["WAXAL_REPLY_LANGUAGE"] = "en"
