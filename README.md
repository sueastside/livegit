#LiveGit

##What is it?

Did you ever wish your working copy was live? You have a solution that pulls from git, but constantly committing and pushing your code is slowing you down?

##Use cases

#####Jenkins DSL script development

* Start LiveGit, change your job to pull from your Livegit git repo.
* Install Jenkins Control plugin in intellij (https://plugins.jetbrains.com/plugin/6110-jenkins-control)
* Favorite your job.
* Make your code changes.
* Double click your job to build.


#####Anything else?

###Installation
```
git clone url
pip install -r requirements.txt
```
Todo: packaging

###Help
```
usage: livegit.py [-h] [--path PATH] [--port PORT]

optional arguments:
  -h, --help   show this help message and exit
  --path PATH  The path to watch for changes
  --port PORT  The port to run the server on
```